# Status

Last updated: 2026-08-20

## Current state
Steps 1-6 built and committed (latest storage change not yet pushed).
Full pipeline verified end-to-end live, including the success path.

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
  `POST /resumes` uploads pdf/docx (now to Storage) and enqueues;
  `GET /resumes/{id}` returns status/result/error. Never calls the LLM.
- `worker/run.py`: polls the queue, downloads from Storage, calls
  `parse_resume`, marks done/failed. Only process that calls the LLM.
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
1. Decide when to cut over `file_data`: make it nullable, stop writing
   it, eventually drop the column — intentionally deferred until the
   storage_path path is proven out further.
2. Search (hybrid keyword + semantic) — not started. Core to the
   project's pitch but no build-order step or design yet.
3. Step 7 — deploy.
