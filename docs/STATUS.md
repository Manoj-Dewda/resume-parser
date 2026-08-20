# Status

Last updated: 2026-08-20

## Current state
Steps 1-6 built, committed, and pushed to origin/main. Full pipeline
verified end-to-end live, including the success path.

- Parser (`packages/parser/`) targets `gemini-3.5-flash`. Eval baseline
  is **confirmed on the real model: 97.0% overall**. Weakest fields:
  `location` 90.0%, `education.graduation_date` 90.5%,
  `position.start_date` 92.8%. `eval/score.py` takes `--model` (target
  any model) and `--skip-scored` (resume a run that got cut off instead
  of losing all progress).
- Postgres/Supabase queue (`db/jobs.py`, `db/migrations/`): enqueue,
  claim (`FOR UPDATE SKIP LOCKED`), done/failed, status lookup — live
  and verified.
- **Resume binaries now live in Supabase Storage, not Postgres**
  (`storage.py`, migration `0002_add_storage_path.sql`). Postgres was
  doing triple duty as database + queue + blob store, eating into
  Supabase Free's 500MB DB storage instead of its separate 1GB file
  storage. The API uploads to Storage and enqueues with `storage_path`;
  the worker downloads from `storage_path` instead of reading
  `file_data`. `file_data` is deliberately still dual-written for now as
  a safety net — dropping it (making it nullable, then removing the
  column) is an intentional separate follow-up, not done yet. Verified
  live: upload lands in the Storage bucket at the right size, worker
  downloads from there (not the DB blob) and parses correctly.
- `api/main.py` (FastAPI, CORS enabled for `localhost:3000`):
  `POST /resumes` uploads pdf/docx (now to Storage) and enqueues, capped
  at `MAX_RESUME_SIZE_MB` (default 5) — rejected via a Content-Length
  check before the body is even parsed, plus a chunked-read backstop for
  requests without one, so an oversized upload never gets fully buffered.
  `GET /resumes/{id}` returns status/result/error. Never calls the LLM.
- `worker/run.py`: polls the queue, downloads from Storage, calls
  `parse_resume`, marks done/failed. Only process that calls the LLM.
  Now has three layers of resilience, all live-verified with real rows:
  inline exponential-backoff retry for transient errors within one claim
  (`parse_with_retry`, classification grounded in `google-genai`'s own
  source, not guessed — e.g. `501` is deliberately excluded from retry
  even though it's a 5xx, since the SDK itself treats it as permanent);
  queue-level retry reusing the existing `attempts` column
  (`MAX_ATTEMPTS`, default 3 — no new counter added) for failures that
  survive that; and stale-lock recovery reusing the existing `locked_at`
  column (`reap_stale_jobs`, `PROCESSING_TIMEOUT_SECONDS`, default 600s)
  for a worker that crashes or hangs mid-job. Concurrency is now
  configurable (`WORKER_CONCURRENCY`, default 1) — each unit is a full
  poll loop in its own thread with its own DB connection and Gemini
  client. Measured live with real jobs through the full stack:
  4 jobs took 37.4s at concurrency 1 vs 26.8s at concurrency 4.
  **Discovered in that same test: `gemini-3.5-flash`'s free tier caps at
  5 requests/minute** (seen verbatim in a 429's `quotaValue`) — at
  concurrency 4 we already hit it (2 of 4 requests got rate-limited and
  had to retry), so 4 looks close to the practical ceiling on this tier,
  not just a conservative starting point. Retries absorbed it cleanly;
  all 4 jobs still completed.
- `web/` (Next.js + Tailwind): upload page verified live in a real
  browser — pending/polling state and the completed parsed-result view
  both render correctly, zero console/CORS errors. File-input bug found
  during manual testing (a click was getting intercepted by something
  else on the page) fixed with the standard hidden-input + button
  pattern.
- `dev.sh`: starts/stops API + worker + frontend together, since
  forgetting to restart one of the three after a stop caused confusing
  "stuck"/"failed to fetch" bugs more than once.

## Next up

### 1. `file_data` cutover — keep-until / delete-when criteria
Right now every upload still dual-writes: the full binary goes to both
`file_data` (Postgres) and Storage (`storage_path`). That's deliberate,
not forgotten — `file_data` is the rollback safety net while
`storage_path` is new and only lightly exercised (one live test so far).

**Keep `file_data` (don't touch it) until all of these hold:**
- `storage_path` has been exercised across several more real uploads,
  covering both `.pdf` and `.docx`, with no download/parse failures
  traceable to Storage itself (a Gemini-side failure like a 429/503 is
  fine and unrelated — this is specifically about the Storage read path).
- No job in the table predates the migration and still lacks a
  `storage_path` — check via `SELECT count(*) FROM resumes WHERE
  storage_path IS NULL`; should be 0 before cutting over.
- The worker's `claimed.file_data` fallback branch (used only when
  `storage_path` is absent) has had a chance to sit unused for a while,
  confirming nothing still depends on it.

**Cutover, once those hold — in this order, each as its own step:**
1. Stop writing `file_data` in `api/main.py`'s `enqueue` call.
2. New migration: `ALTER TABLE resumes ALTER COLUMN file_data DROP NOT NULL`.
3. Verify a real upload still works end-to-end with `file_data` no
   longer populated for new rows.
4. Only after that's proven out: a final migration to `DROP COLUMN
   file_data` entirely, and delete the now-dead fallback branch in
   `worker/run.py`.

Do not skip straight to step 4. Each step should be its own reviewed
change, not one big diff — this is exactly the kind of cutover where
"looked fine in the diff" and "actually fine in production" can diverge.

### 2. Other next steps
- Search (hybrid keyword + semantic) — not started. Core to the
  project's pitch but no build-order step or design yet.
- Step 7 — deploy.
