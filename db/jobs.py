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
    attempts: int


def enqueue(
    conn: psycopg.Connection,
    original_filename: str,
    file_type: Literal["pdf", "docx"],
    file_data: bytes,
) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO resumes (original_filename, file_type, file_data)
            VALUES (%s, %s, %s)
            RETURNING id
            """,
            (original_filename, file_type, file_data),
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
            RETURNING id, original_filename, file_type, file_data, attempts
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
        attempts=row[4],
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
