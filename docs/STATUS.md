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

### 1. `file_data` cutover — in progress
Steps 1-2 done: `api/main.py` no longer writes `file_data` on new
uploads (`db/jobs.py`'s `enqueue` dropped the parameter entirely), and
migration `0004_make_file_data_nullable.sql` dropped the `NOT NULL`
constraint so those inserts succeed. Verified live: uploaded both a
`.docx` and a `.pdf`, confirmed `file_data IS NULL` on the new rows,
and confirmed Supabase Storage download returns byte-identical content
for both file types.

Remaining: step 3, a final migration to `DROP COLUMN file_data`
entirely and delete the now-dead `claimed.file_data` fallback branch in
`worker/run.py`. Not done yet — the table was empty at cutover time (no
legacy rows to worry about either way), but dropping a column outright
is the one step here that isn't easily undone, so it's kept as its own
separate, explicitly-approved change rather than bundled with steps 1-2.

### 2. Raw-file retention — design only, not implemented
No automatic (or manual) deletion exists yet, and none should be added
until the product requirement — how long a raw resume needs to exist
after parsing — is actually decided. This is just confirming the
storage layer doesn't block adding it later, without building it now.

**Already true today, no changes needed:**
- The raw binary (Storage, `storage_path`) and the parsed result
  (Postgres, `parsed_result` JSONB) are fully decoupled — confirmed as
  part of the `file_data` cutover above. Deleting the Storage object
  for a `done` row cannot lose parsed data; they don't share storage.
- `storage_path` is already a nullable column, so "file deleted" can
  be represented by setting it to `NULL` — no new "deleted" flag or
  column required.
- `updated_at` is already bumped to `now()` by `mark_done` (see
  `db/jobs.py`), so "how long ago did this finish" for a `done` row is
  just `now() - updated_at` — no new "completed_at" timestamp needed,
  same reasoning as the metrics work above.
- `GET /resumes/{id}` (`api/main.py`) never returns `storage_path` to
  the client, so nulling it out later changes nothing about the API's
  response shape.

**What a future cleanup policy would look like, once a retention
period is confirmed:** find `done` rows with `storage_path IS NOT NULL
AND updated_at < now() - interval '<retention>'`, delete each Storage
object, then set that row's `storage_path` to `NULL`. That's a query
against columns that already exist — no schema change required to
turn it on.

**Deliberately not built:** the query above, any script or cron to run
it, and any column/flag beyond what's listed. Building it now would be
implementing a policy that hasn't been confirmed.

### 3. Other next steps
- Search (hybrid keyword + semantic) — not started. Core to the
  project's pitch but no build-order step or design yet.
- Step 7 — deploy. Architecture decided (Vercel for the frontend,
  Render Free running the API and worker together in one Web Service,
  since Render has no free instance type for a separate Background
  Worker) and written up in `docs/DEPLOY.md`, but nothing has actually
  been provisioned yet.
