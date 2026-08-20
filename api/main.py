"""HTTP API. Enqueues resume uploads and reports job status.

Never calls the LLM directly — a resume is parsed by the separate worker
process (worker/run.py), which polls the queue and calls packages/parser.
"""

import os
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from typing import Annotated, Literal

import psycopg
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from psycopg_pool import ConnectionPool

from db.jobs import enqueue, get_resume
from storage import upload_resume as upload_to_storage

load_dotenv()

# Measured, not assumed: a fresh psycopg.connect() against Supabase's pooler
# from here averaged ~1.8s (connect + one query + close) vs ~0.26s for a
# query on an already-open connection — about 1.5s of pure connection setup
# eaten on every single request under the old per-request connect(). Small
# and fixed rather than scaled to expected traffic: this is a low-volume
# personal project, and Supabase Free's connection limit is a shared,
# scarce resource — reuse connections, don't provision for load that
# doesn't exist yet.
API_DB_POOL_MAX_SIZE = int(os.environ.get("API_DB_POOL_MAX_SIZE", "5"))


def get_database_url() -> str:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL not set. Copy .env.example to .env and fill it in.")
    return database_url


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    with ConnectionPool(
        get_database_url(), min_size=1, max_size=API_DB_POOL_MAX_SIZE, open=True
    ) as pool:
        app.state.db_pool = pool
        yield


app = FastAPI(lifespan=lifespan)

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


def get_connection(request: Request) -> Iterator[psycopg.Connection]:
    """Borrows a connection from the pool for this request only, returning it
    when the request finishes (or errors) — not one held for the process's
    whole lifetime, and not a fresh connect() per request either."""
    with request.app.state.db_pool.connection() as conn:
        yield conn


DbConnection = Annotated[psycopg.Connection, Depends(get_connection)]


@app.post("/resumes")
async def upload_resume(file: UploadFile, conn: DbConnection):
    if not file.filename:
        raise HTTPException(status_code=400, detail="file must have a filename")

    _, _, extension = file.filename.rpartition(".")
    file_type = EXTENSION_TO_FILE_TYPE.get(f".{extension.lower()}")
    if file_type is None:
        raise HTTPException(status_code=400, detail="only .pdf and .docx files are supported")

    file_data = await read_upload(file, MAX_RESUME_SIZE_BYTES)
    storage_path = upload_to_storage(file_data, file.filename)

    resume_id = enqueue(conn, file.filename, file_type, file_data, storage_path)

    return {"id": resume_id, "status": "pending"}


@app.get("/resumes/{resume_id}")
async def get_resume_status(resume_id: int, conn: DbConnection):
    resume = get_resume(conn, resume_id)

    if resume is None:
        raise HTTPException(status_code=404, detail="resume not found")

    return {
        "id": resume.id,
        "status": resume.status,
        "parsed_result": resume.parsed_result,
        "error": resume.error,
    }
