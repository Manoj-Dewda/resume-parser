# Status

Last updated: 2026-08-18

## Current state
Build order steps 1-3 done. First baseline accuracy number exists.

- `eval/corpus/`: all 20 synthetic resume/ground-truth pairs generated.
- `packages/parser/`: pure-library parser built (`models.py`,
  `extract_text.py`, `parse.py` — `parse_resume(client, data, file_type)
  -> Resume` via Gemini structured output, model `gemini-3.5-flash`).
- `eval/score.py`: parses every corpus resume, best-fit matches predicted
  vs. ground-truth `positions`/`education` entries, scores scalar fields
  by normalized exact match and `skills` by F1, prints per-field accuracy,
  writes `eval/results.json`. Retries on 429 rate limits.
- Baseline (run against `gemini-3.5-flash-lite` as a one-time stopgap —
  `gemini-3.5-flash`'s daily quota was exhausted; `parse.py` itself is
  unchanged and still set to `gemini-3.5-flash`): **96.6% overall**.
  Weakest fields: `location` 90.0%, `education.graduation_date` 90.5%,
  `position.company`/`position.start_date` 92.8%.

## Next up
1. Re-run `eval/score.py` against real `gemini-3.5-flash` once its daily
   quota resets, to confirm the baseline holds on the production model.
2. Build order step 4 — Postgres schema + job queue.

## Known issues
Current 96.6% baseline was measured on `flash-lite`, not `flash` (quota).
Treat as provisional until confirmed on the production model.

## Open questions
None.
