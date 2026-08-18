"""Score the parser against the corpus and report field-level accuracy.

Parses every eval/corpus/resume_NN.txt with the current parser, compares the
result to the matching resume_NN.json ground truth, and prints per-field
accuracy averaged across the whole corpus. Also writes eval/results.json
with per-resume detail, so a before/after parser change can be diffed.
"""

import argparse
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import errors
from parser import Resume, parse_resume_text

CORPUS_DIR = Path(__file__).parent / "corpus"
RESULTS_PATH = Path(__file__).parent / "results.json"

SCALAR_FIELDS = ["name", "email", "phone", "location"]
POSITION_FIELDS = ["title", "company", "start_date", "end_date", "is_current"]
EDUCATION_FIELDS = ["degree", "institution", "graduation_date"]
MAX_RETRIES = 5
RETRY_BASE_DELAY_SECONDS = 10
DEFAULT_MODEL = "gemini-3.5-flash"


def parse_args() -> argparse.Namespace:
    arg_parser = argparse.ArgumentParser(description="Score the parser against the eval corpus.")
    arg_parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help="Gemini model to evaluate against (default: %(default)s)",
    )
    arg_parser.add_argument(
        "--skip-scored",
        action="store_true",
        help=(
            "Skip resumes already scored under this model in eval/results.json, "
            "continuing a run that was cut short (e.g. by a quota error)"
        ),
    )
    return arg_parser.parse_args()


def normalize(value):
    return value.strip().casefold() if isinstance(value, str) else value


def build_client() -> genai.Client:
    load_dotenv()
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set. Copy .env.example to .env and fill it in.")
    return genai.Client(api_key=api_key)


def parse_with_retry(client: genai.Client, resume_text: str, model: str) -> Resume:
    for attempt in range(MAX_RETRIES):
        try:
            return parse_resume_text(client, resume_text, model=model)
        except errors.ClientError as e:
            if e.code != 429 or attempt == MAX_RETRIES - 1:
                raise
            delay = RETRY_BASE_DELAY_SECONDS * (2**attempt)
            print(f"  rate limited ({e}), retrying in {delay}s [{attempt + 1}/{MAX_RETRIES}]")
            time.sleep(delay)
    raise AssertionError("unreachable")


def match_entries(predicted: list, truth: list, fields: list[str]) -> list[tuple]:
    """Greedily pair predicted/truth entries, best-scoring pair first, by
    number of matching normalized fields. Leftover entries on either side
    pair with None (a missing or a hallucinated/extra entry)."""
    candidates = [
        (sum(normalize(getattr(p, f)) == normalize(getattr(t, f)) for f in fields), pi, ti)
        for pi, p in enumerate(predicted)
        for ti, t in enumerate(truth)
    ]
    candidates.sort(key=lambda c: -c[0])

    used_pred, used_truth, pairs = set(), set(), []
    for _, pi, ti in candidates:
        if pi in used_pred or ti in used_truth:
            continue
        used_pred.add(pi)
        used_truth.add(ti)
        pairs.append((predicted[pi], truth[ti]))

    pairs += [(p, None) for pi, p in enumerate(predicted) if pi not in used_pred]
    pairs += [(None, t) for ti, t in enumerate(truth) if ti not in used_truth]
    return pairs


def score_list_field(predicted: list, truth: list, fields: list[str]) -> dict[str, list[bool]]:
    scores = {f: [] for f in fields}
    for pred, truth_entry in match_entries(predicted, truth, fields):
        for f in fields:
            matched = (
                pred is not None
                and truth_entry is not None
                and normalize(getattr(pred, f)) == normalize(getattr(truth_entry, f))
            )
            scores[f].append(matched)
    return scores


def score_skills(predicted: list[str], truth: list[str]) -> float:
    pred_set = {normalize(s) for s in predicted}
    truth_set = {normalize(s) for s in truth}
    if not pred_set and not truth_set:
        return 1.0
    if not pred_set or not truth_set:
        return 0.0
    intersection = pred_set & truth_set
    precision = len(intersection) / len(pred_set)
    recall = len(intersection) / len(truth_set)
    return 2 * precision * recall / (precision + recall)


def score_resume(predicted: Resume, truth: Resume) -> dict:
    scores = {
        f: normalize(getattr(predicted, f)) == normalize(getattr(truth, f)) for f in SCALAR_FIELDS
    }
    scores["skills_f1"] = score_skills(predicted.skills, truth.skills)
    position_scores = score_list_field(predicted.positions, truth.positions, POSITION_FIELDS)
    for f, values in position_scores.items():
        scores[f"position.{f}"] = values
    education_scores = score_list_field(predicted.education, truth.education, EDUCATION_FIELDS)
    for f, values in education_scores.items():
        scores[f"education.{f}"] = values
    return scores


def aggregate_scores(all_scores: list[dict]) -> dict[str, float]:
    """Average every field's score(s), across every resume, into one accuracy number per field."""
    buckets: dict[str, list[float]] = {}
    for scores in all_scores:
        for key, value in scores.items():
            values = value if isinstance(value, list) else [value]
            buckets.setdefault(key, []).extend(float(v) for v in values)
    return {key: sum(values) / len(values) for key, values in buckets.items()}


def compute_aggregate(per_resume: list[dict]) -> tuple[dict[str, float], float]:
    aggregate = aggregate_scores([r["scores"] for r in per_resume])
    overall = sum(aggregate.values()) / len(aggregate)
    return aggregate, overall


def write_results(model: str, per_resume: list[dict]) -> None:
    aggregate, overall = compute_aggregate(per_resume)
    RESULTS_PATH.write_text(
        json.dumps(
            {
                "generated_at": datetime.now(UTC).isoformat(),
                "model": model,
                "overall": overall,
                "aggregate": aggregate,
                "per_resume": per_resume,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def load_already_scored(model: str) -> dict[str, dict]:
    """Resumes already scored under `model` in an existing results.json, keyed
    by stem. Empty if the file is missing or was scored under a different
    model — a resumed run must never mix scores from two different models."""
    if not RESULTS_PATH.exists():
        return {}
    data = json.loads(RESULTS_PATH.read_text())
    if data.get("model") != model:
        return {}
    return {entry["resume"]: entry for entry in data["per_resume"]}


def main() -> None:
    args = parse_args()
    client = build_client()
    resume_paths = sorted(CORPUS_DIR.glob("resume_*.txt"))

    already_scored = load_already_scored(args.model) if args.skip_scored else {}
    per_resume = list(already_scored.values())

    for txt_path in resume_paths:
        stem = txt_path.stem
        if stem in already_scored:
            print(f"skipping {stem}  [already scored]")
            continue
        truth = Resume.model_validate_json((CORPUS_DIR / f"{stem}.json").read_text())
        predicted = parse_with_retry(client, txt_path.read_text(), args.model)
        per_resume.append({"resume": stem, "scores": score_resume(predicted, truth)})
        print(f"scored {stem}")
        write_results(args.model, per_resume)

    aggregate, overall = compute_aggregate(per_resume)
    print("\nField-level accuracy (averaged across all resumes):")
    for field, accuracy in sorted(aggregate.items()):
        print(f"  {field:<24} {accuracy:.1%}")
    print(f"  {'overall':<24} {overall:.1%}")
    print(f"\nwrote {RESULTS_PATH}")


if __name__ == "__main__":
    main()
