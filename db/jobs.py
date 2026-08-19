"""Job queue operations on the resumes table.

The queue is just the resumes table itself, filtered by status. A worker
claims a row with SELECT ... FOR UPDATE SKIP LOCKED, so multiple workers can
poll concurrently without ever claiming the same resume twice.
"""

from dataclasses import dataclass
from typing import Literal

import psycopg
from psycopg.types.json import Jsonb


@dataclass
class ClaimedResume:
    id: int
    original_filename: str
    file_type: Literal["pdf", "docx"]
    file_data: bytes
    storage_path: str | None
    attempts: int


@dataclass
class ResumeStatus:
    id: int
    status: Literal["pending", "processing", "done", "failed"]
    parsed_result: dict | None
    error: str | None


def enqueue(
    conn: psycopg.Connection,
    original_filename: str,
    file_type: Literal["pdf", "docx"],
    file_data: bytes,
    storage_path: str,
) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO resumes (original_filename, file_type, file_data, storage_path)
            VALUES (%s, %s, %s, %s)
            RETURNING id
            """,
            (original_filename, file_type, file_data, storage_path),
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
            RETURNING id, original_filename, file_type, file_data, storage_path, attempts
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
        file_data=bytes(row[3]),
        storage_path=row[4],
        attempts=row[5],
    )


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
