"""Worker process. Polls the resumes queue and parses claimed jobs.

The only process that calls the LLM — the API only ever enqueues.
"""

import os
import threading
import time
from typing import Literal

import httpx
from dotenv import load_dotenv
from google import genai
from google.genai import errors
from parser import Resume, parse_resume
from psycopg_pool import ConnectionPool

from db.jobs import claim_next, mark_done, mark_failed, reap_stale_jobs, requeue
from storage import download_resume

POLL_INTERVAL_SECONDS = 5
MAX_PARSE_ATTEMPTS = 3
RETRY_BASE_DELAY_SECONDS = 5

# Recovers jobs stuck in 'processing' because their worker died mid-job
# (crashed, OOM-killed, or the process was killed) before it ever reached the
# except block that normally calls requeue()/mark_failed(). Must be well
# above how long a legitimate request can take: verified from google-genai's
# source that it sets NO default timeout on its own HTTP requests
# (HttpOptions.timeout is None -> timeout=None is passed straight to httpx,
# which means unbounded) — so there's no SDK-side ceiling to rely on. Worst
# case for a single claim is parse_with_retry's up to ~15s of inline backoff
# plus up to MAX_PARSE_ATTEMPTS request durations; 10 minutes is comfortably
# above any realistic combination of that while still recovering a genuinely
# dead worker in reasonable time for a low-volume, single-worker setup.
PROCESSING_TIMEOUT_SECONDS = int(os.environ.get("PROCESSING_TIMEOUT_SECONDS", "600"))

# Bounds queue-level retries via the existing attempts column (incremented
# once per claim_next call) rather than a separate counter. This is the
# retry layer for failures that survive parse_with_retry's inline attempts —
# e.g. a rate limit that hasn't cleared in 15s, or a fresh transient error on
# a later claim. Default of 3 chosen from what we've actually observed from
# Gemini: brief 503 "high demand" spikes clear within seconds to low minutes
# (parse_with_retry's inline backoff plus a couple of requeue rounds covers
# that), while sustained exhaustion (e.g. the daily free-tier quota) won't
# clear in any of these rounds regardless of the count — 3 fails promptly
# and visibly instead of quietly retrying something that can't succeed soon.
MAX_ATTEMPTS = int(os.environ.get("MAX_ATTEMPTS", "3"))

# Matches google-genai's own definition of retryable failures (see
# _RETRY_HTTP_STATUS_CODES and _HTTPX_TRANSIENT_EXC in the installed
# google.genai._api_client) rather than a blanket >=500 — e.g. 501 Not
# Implemented is a permanent condition, not a transient one, so it's
# deliberately excluded even though it's a 5xx. The SDK does zero retries of
# its own by default (confirmed: genai.Client() with no retry_options means
# every failure reaches this code on the first attempt), so this is the only
# retry layer in effect.
RETRYABLE_HTTP_CODES = {408, 429, 500, 502, 503, 504}
RETRYABLE_NETWORK_ERRORS = (httpx.TimeoutException, httpx.ConnectError)

# Each unit of concurrency is a full poll loop in its own thread. Threads
# share one small ConnectionPool (below) rather than each holding its own
# connection forever — a connection open for a thread's whole lifetime can
# go stale (network blip, Supabase's pooler reaping an idle session) with
# nothing to detect or recover it; the pool health-checks and reconnects.
# Each thread still gets its own Gemini client, since that's an HTTP client
# (its own internal pooling), not a database connection. Safe to raise:
# claim_next's SELECT ... FOR UPDATE SKIP LOCKED was already designed for
# multiple concurrent claimers from day one. NOT safe to raise carelessly:
# Gemini's free-tier rate limits (we've hit both per-minute 429s and a fully
# exhausted daily quota this session) and Supabase's connection limits are
# the real ceiling, not this number. Default of 1 keeps existing behavior
# unless explicitly opted into. Test 1, 2, 4 and measure actual throughput/
# error rate before going higher — don't guess a bigger number.
WORKER_CONCURRENCY = int(os.environ.get("WORKER_CONCURRENCY", "1"))

# Sized to WORKER_CONCURRENCY, not a bigger round number: each thread only
# ever needs one connection checked out at a time (every DB call in
# poll_loop is a short borrow-use-return, never held across a Gemini call),
# so there's no benefit to a bigger pool — and Supabase Free's connection
# ceiling is the exact resource this task said to protect. min_size=1 keeps
# at least one warm connection instead of paying full connect latency on
# the very first claim.
DB_POOL_MIN_SIZE = 1
DB_POOL_MAX_SIZE = WORKER_CONCURRENCY


def is_transient(e: Exception) -> bool:
    """Rate limits, known-transient server errors, and network timeouts/
    connection failures are worth retrying. Anything else — invalid API key,
    bad request, a document Gemini permanently rejects, a schema/parsing
    failure — will just fail the same way again, so don't burn retries on it.
    Verified empirically: an invalid API key raises ClientError(code=400),
    which is correctly non-retryable here."""
    if isinstance(e, errors.APIError):
        return e.code in RETRYABLE_HTTP_CODES
    return isinstance(e, RETRYABLE_NETWORK_ERRORS)


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


def get_database_url() -> str:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL not set. Copy .env.example to .env and fill it in.")
    return database_url


def build_client() -> genai.Client:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set. Copy .env.example to .env and fill it in.")
    return genai.Client(api_key=api_key)


def poll_loop(worker_id: int, pool: ConnectionPool) -> None:
    def log(msg: str) -> None:
        print(f"[worker {worker_id}] {msg}")

    client = build_client()

    log("started, polling for jobs")
    while True:
        with pool.connection() as conn:
            recovered, reaped_failed = reap_stale_jobs(
                conn, PROCESSING_TIMEOUT_SECONDS, MAX_ATTEMPTS
            )
        if recovered or reaped_failed:
            log(f"reaped stale jobs: {recovered} recovered, {reaped_failed} failed")

        with pool.connection() as conn:
            claimed = claim_next(conn)
        if claimed is None:
            time.sleep(POLL_INTERVAL_SECONDS)
            continue

        log(f"claimed resume {claimed.id} ({claimed.original_filename})")
        try:
            # storage_path is the primary read path now; file_data is kept only
            # as a fallback for any pre-migration rows until it's dropped.
            file_data = (
                download_resume(claimed.storage_path) if claimed.storage_path else claimed.file_data
            )
            resume = parse_with_retry(client, file_data, claimed.file_type)
            with pool.connection() as conn:
                mark_done(conn, claimed.id, resume.model_dump())
            log(f"done resume {claimed.id}")
        except Exception as e:
            if is_transient(e) and claimed.attempts < MAX_ATTEMPTS:
                with pool.connection() as conn:
                    requeue(conn, claimed.id)
                progress = f"{claimed.attempts}/{MAX_ATTEMPTS}"
                log(f"requeued resume {claimed.id} (attempt {progress}): {e}")
            else:
                with pool.connection() as conn:
                    mark_failed(conn, claimed.id, str(e))
                log(f"failed resume {claimed.id} after {claimed.attempts} attempt(s): {e}")


def run() -> None:
    load_dotenv()
    print(f"starting {WORKER_CONCURRENCY} worker thread(s)")
    with ConnectionPool(
        get_database_url(),
        min_size=DB_POOL_MIN_SIZE,
        max_size=DB_POOL_MAX_SIZE,
        open=True,
    ) as pool:
        threads = [
            threading.Thread(target=poll_loop, args=(i, pool), daemon=True)
            for i in range(WORKER_CONCURRENCY)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()


if __name__ == "__main__":
    run()
