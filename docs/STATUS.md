# Status

Last updated: 2026-08-19

## Current state
Steps 1-6 built and committed (not pushed). Step 5/6 verified live but
with one recurring gap: the real success path is still unconfirmed.

- Parser (`packages/parser/`) targets `gemini-3.5-flash`. Eval baseline
  is **96.6% overall**, but that number was measured on
  `gemini-3.5-flash-lite` (a stopgap for exhausted `flash` quota) —
  still unconfirmed on the real target model. `eval/score.py` now takes
  `--model` (target any model) and `--skip-scored` (resume a run that
  got cut off instead of losing all progress).
- Postgres/Supabase queue (`db/jobs.py`, `db/migrations/`) is live and
  verified: enqueue, claim (`FOR UPDATE SKIP LOCKED`), done/failed,
  status lookup.
- `api/main.py` (FastAPI, CORS enabled for `localhost:3000`):
  `POST /resumes` uploads pdf/docx and enqueues; `GET /resumes/{id}`
  returns status/result/error. Never calls the LLM.
- `worker/run.py`: polls the queue, calls `parse_resume`, marks
  done/failed. Only process that calls the LLM.
- `web/` (Next.js + Tailwind): upload page that posts to the API and
  polls for status. Verified live in a headless browser — upload
  succeeds, polling starts automatically, no CORS/console errors.
- The one thing still not verified anywhere: a job actually completing.
  Every live test so far has hit the exhausted `gemini-3.5-flash` daily
  quota, so `mark_done` and the parsed-result UI are both
  code-reviewed only, not exercised.

## Next up
1. Once the `gemini-3.5-flash` daily quota resets, run
   `uv run python eval/score.py --skip-scored` for a confirmed baseline.
   Same run also unblocks verifying the worker's `mark_done` path and
   the UI's parsed-result view for the first time.
2. Search (hybrid keyword + semantic) — not started. Core to the
   project's pitch but no build-order step or design yet.
3. Step 7 — deploy.
