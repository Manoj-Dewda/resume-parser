# Status

Last updated: 2026-08-19

## Current state
Steps 1-6 built and committed (not pushed).

- Parser (`packages/parser/`) targets `gemini-3.5-flash`. Eval baseline
  is **confirmed on the real model: 97.0% overall** (previously only a
  96.6% provisional number from `gemini-3.5-flash-lite`, matches closely).
  Weakest fields: `location` 90.0%, `education.graduation_date` 90.5%,
  `position.start_date` 92.8%. `eval/score.py` now takes `--model`
  (target any model) and `--skip-scored` (resume a run that got cut off
  instead of losing all progress) — used to get this confirmed number
  across an earlier partial-quota interruption.
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
- Still unverified: a job actually completing end-to-end. The eval run
  used the day's `gemini-3.5-flash` quota to get the confirmed baseline
  above, so the worker's `mark_done` path and the UI's parsed-result
  view are both code-reviewed only, likely still blocked until the
  quota resets again.

## Next up
1. Once quota allows, run one real job through worker + UI to verify
   `mark_done` and the parsed-result view for the first time.
2. Search (hybrid keyword + semantic) — not started. Core to the
   project's pitch but no build-order step or design yet.
3. Step 7 — deploy.
