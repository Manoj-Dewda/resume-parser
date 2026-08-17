from typing import Literal

from google import genai
from google.genai import types

from .extract_text import extract_text_from_docx, extract_text_from_pdf
from .models import Resume

MODEL = "gemini-3.5-flash"

PROMPT_TEMPLATE = """\
Extract structured candidate information from the resume text below. Extract \
only facts stated in the text; do not infer or invent anything absent from it.

Normalize `start_date`, `end_date`, and `graduation_date` to "YYYY-MM" if the \
text states a month, otherwise "YYYY". For any position the text marks as \
ongoing (e.g. "Present"), use is_current=true and end_date="".

Resume text:
{resume_text}
"""


def parse_resume_text(client: genai.Client, resume_text: str) -> Resume:
    response = client.models.generate_content(
        model=MODEL,
        contents=PROMPT_TEMPLATE.format(resume_text=resume_text),
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=Resume,
            temperature=0,
        ),
    )
    return Resume.model_validate_json(response.text)


def parse_resume(client: genai.Client, data: bytes, file_type: Literal["pdf", "docx"]) -> Resume:
    if file_type == "pdf":
        resume_text = extract_text_from_pdf(data)
    elif file_type == "docx":
        resume_text = extract_text_from_docx(data)
    else:
        raise ValueError(f"unsupported file_type: {file_type!r}")
    return parse_resume_text(client, resume_text)
