"""Job queue operations on the resumes table.

The queue is just the resumes table itself, filtered by status. A worker
claims a row with SELECT ... FOR UPDATE SKIP LOCKED, so multiple workers can
poll concurrently without ever claiming the same resume twice.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

import psycopg
from psycopg.types.json import Jsonb


@dataclass
class ClaimedResume:
    id: int
    original_filename: str
    file_type: Literal["pdf", "docx"]
    file_data: bytes | None
    storage_path: str | None
    attempts: int
    created_at: datetime
    locked_at: datetime


@dataclass
class ResumeStatus:
    id: int
    status: Literal["pending", "processing", "done", "failed"]
    parsed_result: dict | None
    error: str | None


@dataclass
class QueueMetrics:
    pending: int
    processing: int
    done: int
    failed: int
    retried: int
    avg_processing_seconds: float | None
    min_processing_seconds: float | None
    max_processing_seconds: float | None


def enqueue(
    conn: psycopg.Connection,
    original_filename: str,
    file_type: Literal["pdf", "docx"],
    storage_path: str,
) -> int:
    """The binary goes to Supabase Storage only (storage_path) — Postgres
    keeps just the job row. file_data stays NULL for every new upload; it
    remains nullable only for whatever pre-cutover rows may still exist."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO resumes (original_filename, file_type, storage_path)
            VALUES (%s, %s, %s)
            RETURNING id
            """,
            (original_filename, file_type, storage_path),
        )
        resume_id = cur.fetchone()[0]
    conn.commit()
    return resume_id


def claim_next(conn: psycopg.Connection) -> ClaimedResume | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE resumes
            SET status = 'processing', locked_at = now(), attempts = attempts + 1,
                updated_at = now()
            WHERE id = (
                SELECT id FROM resumes
                WHERE status = 'pending'
                ORDER BY created_at
                FOR UPDATE SKIP LOCKED
                LIMIT 1
            )
            RETURNING id, original_filename, file_type, file_data, storage_path, attempts,
                      created_at, locked_at
            """
        )
        row = cur.fetchone()
    conn.commit()
    if row is None:
        return None
    return ClaimedResume(
        id=row[0],
        original_filename=row[1],
        file_type=row[2],
        file_data=bytes(row[3]) if row[3] is not None else None,
        storage_path=row[4],
        attempts=row[5],
        created_at=row[6],
        locked_at=row[7],
    )


def reap_stale_jobs(
    conn: psycopg.Connection, timeout_seconds: int, max_attempts: int
) -> tuple[int, int]:
    """Recovers jobs stuck in 'processing' because their worker died (crashed,
    OOM-killed, or hung on a request) without ever reaching the except block
    in worker/run.py that normally calls requeue()/mark_failed(). A row past
    the timeout with retries left goes back to 'pending' for another worker
    to claim; one that's already exhausted attempts is marked failed instead
    of being recovered forever. Returns (recovered_count, failed_count)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE resumes
            SET status = 'failed', error = 'worker crashed or timed out repeatedly',
                updated_at = now()
            WHERE status = 'processing'
              AND locked_at < now() - make_interval(secs => %s)
              AND attempts >= %s
            """,
            (timeout_seconds, max_attempts),
        )
        failed_count = cur.rowcount

        cur.execute(
            """
            UPDATE resumes
            SET status = 'pending', updated_at = now()
            WHERE status = 'processing'
              AND locked_at < now() - make_interval(secs => %s)
              AND attempts < %s
            """,
            (timeout_seconds, max_attempts),
        )
        recovered_count = cur.rowcount
    conn.commit()
    return recovered_count, failed_count


def mark_done(conn: psycopg.Connection, resume_id: int, parsed_result: dict) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE resumes
            SET status = 'done', parsed_result = %s, updated_at = now()
            WHERE id = %s
            """,
            (Jsonb(parsed_result), resume_id),
        )
    conn.commit()


def get_resume(conn: psycopg.Connection, resume_id: int) -> ResumeStatus | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, status, parsed_result, error FROM resumes WHERE id = %s",
            (resume_id,),
        )
        row = cur.fetchone()
    if row is None:
        return None
    return ResumeStatus(id=row[0], status=row[1], parsed_result=row[2], error=row[3])


def requeue(conn: psycopg.Connection, resume_id: int) -> None:
    """Puts a resume back to 'pending' after a transient failure, so a later
    claim_next picks it up again. attempts isn't touched here — it's already
    incremented once per claim_next call, which is what bounds the retry."""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE resumes SET status = 'pending', updated_at = now() WHERE id = %s",
            (resume_id,),
        )
    conn.commit()


def heartbeat(conn: psycopg.Connection, worker_id: int) -> None:
    """Upserted by a worker thread once per poll loop iteration. A thread
    stuck on a hung request (Gemini sets no request timeout) simply stops
    advancing its row, which is the staleness signal /health/worker reads."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO worker_heartbeats (worker_id, updated_at)
            VALUES (%s, now())
            ON CONFLICT (worker_id) DO UPDATE SET updated_at = now()
            """,
            (worker_id,),
        )
    conn.commit()


def latest_worker_heartbeat(conn: psycopg.Connection) -> datetime | None:
    with conn.cursor() as cur:
        cur.execute("SELECT max(updated_at) FROM worker_heartbeats")
        row = cur.fetchone()
    return row[0] if row else None


def get_queue_metrics(conn: psycopg.Connection) -> QueueMetrics:
    """Aggregates queue depth, throughput, and retry stats from columns that
    already exist — no separate metrics table or timestamps. Processing
    duration is derived as updated_at - locked_at on 'done' rows (locked_at
    is set once, at claim time, and never touched again while processing;
    updated_at is bumped by the mark_done that ends it)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                count(*) FILTER (WHERE status = 'pending'),
                count(*) FILTER (WHERE status = 'processing'),
                count(*) FILTER (WHERE status = 'done'),
                count(*) FILTER (WHERE status = 'failed'),
                count(*) FILTER (WHERE attempts > 1),
                avg(extract(epoch FROM updated_at - locked_at)) FILTER (WHERE status = 'done'),
                min(extract(epoch FROM updated_at - locked_at)) FILTER (WHERE status = 'done'),
                max(extract(epoch FROM updated_at - locked_at)) FILTER (WHERE status = 'done')
            FROM resumes
            """
        )
        row = cur.fetchone()
    return QueueMetrics(
        pending=row[0],
        processing=row[1],
        done=row[2],
        failed=row[3],
        retried=row[4],
        avg_processing_seconds=float(row[5]) if row[5] is not None else None,
        min_processing_seconds=float(row[6]) if row[6] is not None else None,
        max_processing_seconds=float(row[7]) if row[7] is not None else None,
    )


def mark_failed(conn: psycopg.Connection, resume_id: int, error: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE resumes
            SET status = 'failed', error = %s, updated_at = now()
            WHERE id = %s
            """,
            (error, resume_id),
        )
    conn.commit()
