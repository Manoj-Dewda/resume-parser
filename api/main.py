"""HTTP API. Enqueues resume uploads and reports job status.

Never calls the LLM directly — a resume is parsed by the separate worker
process (worker/run.py), which polls the queue and calls packages/parser.
"""

import os
from typing import Literal

import psycopg
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from db.jobs import enqueue, get_resume
from storage import upload_resume as upload_to_storage

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

# 5 MB default — real resumes are almost always well under 1 MB, so this is
# generous headroom rather than a tight fit. Configurable since "generous"
# depends on what you're willing to store/parse; override via env if needed.
MAX_RESUME_SIZE_MB = int(os.environ.get("MAX_RESUME_SIZE_MB", "5"))
MAX_RESUME_SIZE_BYTES = MAX_RESUME_SIZE_MB * 1024 * 1024
UPLOAD_CHUNK_SIZE = 1024 * 1024


@app.middleware("http")
async def reject_oversized_uploads(request: Request, call_next):
    # Cheap first line of defense: if the client sent an honest Content-Length
    # (nearly all do), reject before Starlette even parses the multipart body
    # — this is what actually stops an oversized upload from being buffered
    # to memory/disk at all, not just from being read by our own code.
    # Content-Length covers the whole multipart body (boundaries + headers,
    # not just the file), so this is a slightly loose upper bound — fine at
    # this size, multipart overhead is negligible next to a few MB.
    if request.method == "POST" and request.url.path == "/resumes":
        content_length = request.headers.get("content-length")
        if content_length is not None and int(content_length) > MAX_RESUME_SIZE_BYTES:
            return JSONResponse(
                status_code=413,
                content={"detail": f"file exceeds maximum size of {MAX_RESUME_SIZE_MB}MB"},
            )
    return await call_next(request)


async def read_upload(file: UploadFile, max_bytes: int) -> bytes:
    """Read in bounded chunks, aborting as soon as the limit is exceeded
    instead of reading (and then discarding) the rest of the file. Backstops
    the Content-Length check above for requests that omit it (e.g. chunked
    transfer-encoding)."""
    data = bytearray()
    while True:
        chunk = await file.read(UPLOAD_CHUNK_SIZE)
        if not chunk:
            break
        data += chunk
        if len(data) > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"file exceeds maximum size of {MAX_RESUME_SIZE_MB}MB",
            )
    return bytes(data)


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

    file_data = await read_upload(file, MAX_RESUME_SIZE_BYTES)
    storage_path = upload_to_storage(file_data, file.filename)

    with get_connection() as conn:
        resume_id = enqueue(conn, file.filename, file_type, file_data, storage_path)

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
