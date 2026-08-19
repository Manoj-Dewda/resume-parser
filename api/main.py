"""HTTP API. Enqueues resume uploads and reports job status.

Never calls the LLM directly — a resume is parsed by the separate worker
process (worker/run.py), which polls the queue and calls packages/parser.
"""

import os
from typing import Literal

import psycopg
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from db.jobs import enqueue, get_resume

load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

EXTENSION_TO_FILE_TYPE: dict[str, Literal["pdf", "docx"]] = {
    ".pdf": "pdf",
    ".docx": "docx",
}


def get_connection() -> psycopg.Connection:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL not set. Copy .env.example to .env and fill it in.")
    return psycopg.connect(database_url)


@app.post("/resumes")
async def upload_resume(file: UploadFile):
    if not file.filename:
        raise HTTPException(status_code=400, detail="file must have a filename")

    _, _, extension = file.filename.rpartition(".")
    file_type = EXTENSION_TO_FILE_TYPE.get(f".{extension.lower()}")
    if file_type is None:
        raise HTTPException(status_code=400, detail="only .pdf and .docx files are supported")

    file_data = await file.read()

    with get_connection() as conn:
        resume_id = enqueue(conn, file.filename, file_type, file_data)

    return {"id": resume_id, "status": "pending"}


@app.get("/resumes/{resume_id}")
async def get_resume_status(resume_id: int):
    with get_connection() as conn:
        resume = get_resume(conn, resume_id)

    if resume is None:
        raise HTTPException(status_code=404, detail="resume not found")

    return {
        "id": resume.id,
        "status": resume.status,
        "parsed_result": resume.parsed_result,
        "error": resume.error,
    }
