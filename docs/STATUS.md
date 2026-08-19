# Status

Last updated: 2026-08-19

## Current state
Steps 1-6 built, committed, and pushed to origin/main. Full pipeline
verified end-to-end live, including the success path.

- Parser (`packages/parser/`) targets `gemini-3.5-flash`. Eval baseline
  is **confirmed on the real model: 97.0% overall** (previously only a
  96.6% provisional number from `gemini-3.5-flash-lite`, matches closely).
  Weakest fields: `location` 90.0%, `education.graduation_date` 90.5%,
  `position.start_date` 92.8%. `eval/score.py` now takes `--model`
  (target any model) and `--skip-scored` (resume a run that got cut off
  instead of losing all progress).
- Postgres/Supabase queue (`db/jobs.py`, `db/migrations/`) is live and
  verified: enqueue, claim (`FOR UPDATE SKIP LOCKED`), done/failed,
  status lookup.
- `api/main.py` (FastAPI, CORS enabled for `localhost:3000`):
  `POST /resumes` uploads pdf/docx and enqueues; `GET /resumes/{id}`
  returns status/result/error. Never calls the LLM.
- `worker/run.py`: polls the queue, calls `parse_resume`, marks
  done/failed. Only process that calls the LLM. **Success path
  (`mark_done`) now verified live** — uploaded a real resume through
  the API, the worker parsed it correctly and saved an accurate
  `parsed_result`.
- `web/` (Next.js + Tailwind): upload page that posts to the API and
  polls for status. **Both states verified live in a real browser**:
  the pending/polling state, and now the completed state — parsed name,
  contact info, skills, experience, and education all render correctly
  with zero console/CORS errors.

## Next up
1. Search (hybrid keyword + semantic) — not started. Core to the
   project's pitch but no build-order step or design yet.
2. Step 7 — deploy.
