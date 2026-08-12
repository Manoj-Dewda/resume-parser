"""Generate a synthetic, deliberately messy resume corpus using the Gemini API.

Writes eval/corpus/resume_NN.txt (the resume as plain text) and a matching
eval/corpus/resume_NN.json (ground-truth structured fields) for each of the
scenarios in SCENARIOS.
"""

import os
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types
from pydantic import BaseModel

MODEL = "gemini-2.5-flash"
CORPUS_DIR = Path(__file__).parent / "corpus"


class Position(BaseModel):
    title: str
    company: str
    start_date: str
    end_date: str
    is_current: bool


class EducationEntry(BaseModel):
    degree: str
    institution: str
    graduation_date: str


class GroundTruth(BaseModel):
    name: str
    email: str
    phone: str
    location: str
    positions: list[Position]
    education: list[EducationEntry]
    skills: list[str]


class ResumeGeneration(BaseModel):
    resume_text: str
    ground_truth: GroundTruth


# Each scenario pins down the messy, real-world characteristics we need
# coverage of. Left to its own devices the model tends toward clean, uniform
# resumes, so heading style / date format / career pattern / region are
# specified explicitly per resume rather than left to chance.
SCENARIOS = [
    dict(
        region="United States",
        heading_style="ALL CAPS section headers, e.g. 'WORK EXPERIENCE', 'EDUCATION'",
        date_format="'Jan 2020 - Present' (abbreviated month + 4-digit year, en dash or hyphen)",
        career_pattern="a normal, continuous career with no gaps or overlaps",
    ),
    dict(
        region="United States",
        heading_style="Title Case headers, e.g. 'Professional Experience', 'Education'",
        date_format="numeric MM/YYYY, e.g. '03/2019 - 06/2021'",
        career_pattern=(
            "one unexplained career gap of 14-18 months between two jobs, "
            "with no role during the gap"
        ),
    ),
    dict(
        region="United Kingdom",
        heading_style=(
            "calls the document a 'Curriculum Vitae' and uses headers like "
            "'Employment History', 'Qualifications'"
        ),
        date_format=(
            "day/month/year numeric, e.g. '14/03/2019 - 21/06/2021', "
            "UK spelling (e.g. 'organisation')"
        ),
        career_pattern="a normal continuous career",
    ),
    dict(
        region="United States",
        heading_style=(
            "no formal headers, just bold-looking inline labels like "
            "'Experience:' and 'Skills:' typed in lowercase"
        ),
        date_format="'Mon YYYY - Mon YYYY', e.g. 'Mar 2018 - Jul 2020'",
        career_pattern=(
            "overlapping roles: freelance/consulting work that ran concurrently "
            "with a full-time job for about a year"
        ),
    ),
    dict(
        region="United States",
        heading_style="ALL CAPS headers",
        date_format="short year ranges, e.g. '2020-21' and '2018-19'",
        career_pattern=(
            "a series of contract/temp roles placed through different staffing "
            "agencies, agency name noted alongside client company name"
        ),
    ),
    dict(
        region="United States",
        heading_style="Title Case headers",
        date_format="abbreviated month with apostrophe year, e.g. 'Jan '20 - Mar '22'",
        career_pattern=(
            "one promotion within a single company: three separate entries at "
            "the same employer with escalating titles and adjoining date ranges"
        ),
    ),
    dict(
        region="India",
        heading_style=(
            "calls the document a 'Curriculum Vitae', headers like "
            "'Career Summary', 'Academic Qualifications'"
        ),
        date_format="'DD Month YYYY', e.g. '12 August 2019 - 04 January 2022'",
        career_pattern="a normal continuous career",
    ),
    dict(
        region="United States",
        heading_style="Title Case headers",
        date_format="season + apostrophe year, e.g. 'Summer '19 - Fall '20'",
        career_pattern=(
            "job-hopping: four or five short stints of well under a year "
            "each at different small companies"
        ),
    ),
    dict(
        region="United States",
        heading_style=(
            "unconventional first-person headers, e.g. 'Where I've Worked', 'What I Know'"
        ),
        date_format="year only, no months, e.g. '2019 - 2021'",
        career_pattern=(
            "one career gap of about two years explicitly explained in a "
            "one-line note (e.g. caregiving or travel) rather than left blank"
        ),
    ),
    dict(
        region="Germany",
        heading_style=(
            "European CV conventions in English, headers like 'Work Experience', "
            "'Education', includes a brief personal-details line"
        ),
        date_format="day.month.year with periods, e.g. '01.09.2018 - 31.03.2021'",
        career_pattern="a normal continuous career",
    ),
    dict(
        region="United States",
        heading_style="minimalist headers marked with dashes, e.g. '--- Experience ---'",
        date_format=(
            "inconsistent within the same resume: some entries use "
            "'Jan 2020 - Present' and others use short year ranges like '2018-19'"
        ),
        career_pattern=(
            "overlapping roles combined with a separate short-term contract "
            "engagement that ran alongside a full-time job"
        ),
    ),
    dict(
        region="United States",
        heading_style="ALL CAPS headers",
        date_format="'Mon YYYY' throughout, e.g. 'Jun 2017 - Aug 2019'",
        career_pattern=(
            "one promotion within a single company (two entries, same employer, "
            "different titles) preceded by an unexplained 8-month gap before that company"
        ),
    ),
    dict(
        region="Australia",
        heading_style="calls the document a 'CV', headers like 'Employment', 'Education'",
        date_format="day/month/year numeric, e.g. '03/02/2019 - 17/11/2021'",
        career_pattern="a normal continuous career",
    ),
    dict(
        region="United States",
        heading_style="Title Case headers",
        date_format="'Mon YYYY - Mon YYYY'",
        career_pattern=(
            "long-term independent contracting: multiple separate client "
            "engagements listed under one self-employed consultancy heading"
        ),
    ),
    dict(
        region="United States",
        heading_style=(
            "minimalist headers, small caps look via mixed case, e.g. 'Experience', 'Skills'"
        ),
        date_format="'Mon YYYY - Mon YYYY'",
        career_pattern=(
            "entry-level candidate: one short internship and one part-time job, "
            "no gaps, very brief work history"
        ),
    ),
    dict(
        region="United States",
        heading_style="unconventional headers, e.g. 'My Journey', 'Tools I Use'",
        date_format="mixes 'Jan 2020 - Present' with year-only entries for older jobs",
        career_pattern=(
            "a career gap of roughly 18 months during which the candidate did "
            "occasional unlisted freelance work, then one overlapping "
            "freelance/full-time period right after returning"
        ),
    ),
    dict(
        region="Philippines",
        heading_style=(
            "headers like 'Career Objective', 'Work Experience', 'Educational Background'"
        ),
        date_format="'Month DD, YYYY', e.g. 'August 12, 2019 - January 04, 2022'",
        career_pattern="a normal continuous career",
    ),
    dict(
        region="United States",
        heading_style="ALL CAPS headers",
        date_format=(
            "mixes 'Mon YYYY - Mon YYYY' for recent roles with short year "
            "ranges like '2015-17' for older roles"
        ),
        career_pattern=(
            "two promotions within one company (three entries, same employer, "
            "escalating titles) plus one earlier, unrelated job at a different company"
        ),
    ),
    dict(
        region="United States",
        heading_style="Title Case headers",
        date_format="'Mon YYYY - Mon YYYY'",
        career_pattern=(
            "contract-to-hire: the same company appears twice, first as a "
            "contractor (via a named staffing agency) then converted to a "
            "full-time title, adjoining dates"
        ),
    ),
    dict(
        region="United States",
        heading_style="ALL CAPS headers, dense and formal",
        date_format="year ranges only, e.g. '1998 - 2004'",
        career_pattern=(
            "a senior executive with a 25+ year career and six or more "
            "positions, otherwise continuous with no gaps"
        ),
    ),
]

PROMPT_TEMPLATE = """\
Generate one realistic but entirely fictional resume for a synthetic evaluation \
dataset used to test a resume-parsing system. The person, employers, and all \
details must be invented; do not base it on any real, identifiable individual.

Candidate profile to embody:
- Region / cultural context: {region}
- Section heading style to use in the resume text: {heading_style}
- Date format to use in the resume text: {date_format}
- Career history pattern: {career_pattern}

Requirements:
1. Invent a full, plausible person: name, email, phone (formatted appropriately \
for the region), location, 2-6 work positions, 1-2 education entries, and \
6-12 skills.
2. Write `resume_text` as plain text the way a real, slightly messy resume \
looks (uneven spacing, abbreviations, informal line breaks are fine, but keep \
it readable). Follow the section heading style and date format described above.
3. Fill `ground_truth` with the exact structured facts `resume_text` expresses: \
the same name, email, phone, location, positions (title, company, start_date, \
end_date, is_current), education, and skills. Normalize `start_date` and \
`end_date` in `ground_truth` to "YYYY-MM" (or "YYYY" if `resume_text` never \
states a month), regardless of how messy the format in `resume_text` is. Use \
is_current=true and end_date="" for any position `resume_text` marks as ongoing \
(e.g. "Present").
4. `ground_truth` must be fully consistent with `resume_text` in substance: \
introduce no fact in one that is absent from the other.
5. The career pattern described above must be clearly visible in `resume_text` \
itself (e.g. a promotion shows up as two or more entries at the same company \
with adjoining dates and different titles; a gap shows up as a visible jump \
between two end/start dates) and must be reflected accurately in `ground_truth`.
"""


def build_client() -> genai.Client:
    load_dotenv()
    api_key = os.environ.get("api_key = os.environ.get("GEMINI_API_KEY")")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set. Copy .env.example to .env and fill it in.")
    return genai.Client(api_key=api_key)


def generate_one(client: genai.Client, scenario: dict) -> ResumeGeneration:
    response = client.models.generate_content(
        model=MODEL,
        contents=PROMPT_TEMPLATE.format(**scenario),
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=ResumeGeneration,
            temperature=1.0,
        ),
    )
    return ResumeGeneration.model_validate_json(response.text)


def main() -> None:
    client = build_client()
    CORPUS_DIR.mkdir(parents=True, exist_ok=True)

    for i, scenario in enumerate(SCENARIOS, start=1):
        result = generate_one(client, scenario)
        stem = f"resume_{i:02d}"
        (CORPUS_DIR / f"{stem}.txt").write_text(result.resume_text, encoding="utf-8")
        (CORPUS_DIR / f"{stem}.json").write_text(
            result.ground_truth.model_dump_json(indent=2), encoding="utf-8"
        )
        print(f"wrote {stem}.txt / {stem}.json  [{scenario['region']}]")


if __name__ == "__main__":
    main()
