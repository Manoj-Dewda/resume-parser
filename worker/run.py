"""Worker process. Polls the resumes queue and parses claimed jobs.

The only process that calls the LLM — the API only ever enqueues.
"""

import os
import time
from typing import Literal

import httpx
import psycopg
from dotenv import load_dotenv
from google import genai
from google.genai import errors
from parser import Resume, parse_resume

from db.jobs import claim_next, mark_done, mark_failed
from storage import download_resume

POLL_INTERVAL_SECONDS = 5
MAX_PARSE_ATTEMPTS = 3
RETRY_BASE_DELAY_SECONDS = 5


def is_transient(e: Exception) -> bool:
    """Rate limits, server-side errors, and network blips are worth retrying.
    Anything else (bad request, auth, a parsing/schema error) will just fail
    the same way again, so don't burn retries on it."""
    if isinstance(e, errors.APIError):
        return e.code == 429 or e.code >= 500
    return isinstance(e, httpx.TransportError)


def parse_with_retry(
    client: genai.Client, file_data: bytes, file_type: Literal["pdf", "docx"]
) -> Resume:
    for attempt in range(MAX_PARSE_ATTEMPTS):
        try:
            return parse_resume(client, file_data, file_type)
        except Exception as e:
            if not is_transient(e) or attempt == MAX_PARSE_ATTEMPTS - 1:
                raise
            delay = RETRY_BASE_DELAY_SECONDS * (2**attempt)
            progress = f"{attempt + 1}/{MAX_PARSE_ATTEMPTS}"
            print(f"  transient error ({e}), retrying in {delay}s [{progress}]")
            time.sleep(delay)
    raise AssertionError("unreachable")


def build_connection() -> psycopg.Connection:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL not set. Copy .env.example to .env and fill it in.")
    return psycopg.connect(database_url)


def build_client() -> genai.Client:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set. Copy .env.example to .env and fill it in.")
    return genai.Client(api_key=api_key)


def run() -> None:
    load_dotenv()
    conn = build_connection()
    client = build_client()

    print("worker started, polling for jobs")
    while True:
        claimed = claim_next(conn)
        if claimed is None:
            time.sleep(POLL_INTERVAL_SECONDS)
            continue

        print(f"claimed resume {claimed.id} ({claimed.original_filename})")
        try:
            # storage_path is the primary read path now; file_data is kept only
            # as a fallback for any pre-migration rows until it's dropped.
            file_data = (
                download_resume(claimed.storage_path) if claimed.storage_path else claimed.file_data
            )
            resume = parse_with_retry(client, file_data, claimed.file_type)
            mark_done(conn, claimed.id, resume.model_dump())
            print(f"done resume {claimed.id}")
        except Exception as e:
            mark_failed(conn, claimed.id, str(e))
            print(f"failed resume {claimed.id}: {e}")


if __name__ == "__main__":
    run()
