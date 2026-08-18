"""Worker process. Polls the resumes queue and parses claimed jobs.

The only process that calls the LLM — the API only ever enqueues.
"""

import os
import time

import psycopg
from dotenv import load_dotenv
from google import genai
from parser import parse_resume

from db.jobs import claim_next, mark_done, mark_failed

POLL_INTERVAL_SECONDS = 5


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
            resume = parse_resume(client, claimed.file_data, claimed.file_type)
            mark_done(conn, claimed.id, resume.model_dump())
            print(f"done resume {claimed.id}")
        except Exception as e:
            mark_failed(conn, claimed.id, str(e))
            print(f"failed resume {claimed.id}: {e}")


if __name__ == "__main__":
    run()
