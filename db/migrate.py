"""Apply SQL migrations in db/migrations/ to the configured Postgres database.

Tracks applied migrations in a schema_migrations table, so re-running only
applies files that haven't been run yet. Each migration runs in its own
transaction.
"""

import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def build_connection() -> psycopg.Connection:
    load_dotenv()
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL not set. Copy .env.example to .env and fill it in.")
    return psycopg.connect(database_url)


def ensure_migrations_table(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                filename TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
    conn.commit()


def applied_migrations(conn: psycopg.Connection) -> set[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT filename FROM schema_migrations")
        return {row[0] for row in cur.fetchall()}


def main() -> None:
    conn = build_connection()
    ensure_migrations_table(conn)
    already_applied = applied_migrations(conn)

    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if path.name in already_applied:
            print(f"skipping {path.name}  [already applied]")
            continue

        with conn.cursor() as cur:
            cur.execute(path.read_text())
            cur.execute("INSERT INTO schema_migrations (filename) VALUES (%s)", (path.name,))
        conn.commit()
        print(f"applied {path.name}")

    conn.close()


if __name__ == "__main__":
    main()
