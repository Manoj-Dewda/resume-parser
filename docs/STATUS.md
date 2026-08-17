# Status

Last updated: 2026-08-18

## Current state
Build order steps 1-4 done, committed, and pushed to origin/main.

- `eval/corpus/` + `packages/parser/`: synthetic corpus and pure-library
  parser (`parse_resume(client, data, file_type) -> Resume`, Gemini
  structured output, model `gemini-3.5-flash`).
- `eval/score.py`: field-level accuracy scorer. Baseline **96.6% overall**
  (measured on `gemini-3.5-flash-lite` as a one-time stopgap — `flash`'s
  daily quota was exhausted; `parse.py` still targets `flash`; treat as
  provisional until confirmed on the real model). Weakest fields:
  `location` 90.0%, `education.graduation_date` 90.5%.
- Postgres is live on Supabase (free tier; direct host is IPv6-only, so
  `DATABASE_URL` uses the session pooler endpoint instead).
  `db/migrations/0001_create_resumes.sql` + `db/migrate.py`: single
  `resumes` table (file bytes, status, attempts, parsed_result jsonb)
  doubling as the queue, applied and verified live.
  `db/jobs.py`: `enqueue`/`claim_next`/`mark_done`/`mark_failed`, using
  `SELECT ... FOR UPDATE SKIP LOCKED`. Smoke-tested live against Supabase
  (FIFO order, concurrent-safe skip, empty-queue `None`) — all correct.

## Next up
1. Re-run `eval/score.py` against real `gemini-3.5-flash` once its daily
   quota resets, to confirm the baseline holds on the production model.
2. Build order step 5 — API (FastAPI, enqueues jobs, never calls the LLM
   directly) plus a worker process to actually drain the queue.

## Known issues
96.6% baseline was measured on `flash-lite`, not `flash` (quota exhaustion).

## Open questions
None.
