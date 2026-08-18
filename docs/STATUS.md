# Status

Last updated: 2026-08-18

## Current state
Steps 1-4 done, committed, pushed to origin/main. Step 5 built and
smoke-tested live, not yet committed.

- Parser (`packages/parser/`) targets `gemini-3.5-flash`. Eval baseline
  is **96.6% overall**, but that number was measured on
  `gemini-3.5-flash-lite` (a stopgap for exhausted `flash` quota) —
  still unconfirmed on the real target model.
- Postgres/Supabase queue (`db/jobs.py`, `db/migrations/`) is live and
  verified: enqueue, claim (`FOR UPDATE SKIP LOCKED`), done/failed,
  status lookup.
- `api/main.py` (FastAPI): `POST /resumes` uploads pdf/docx and
  enqueues; `GET /resumes/{id}` returns status/result/error. Never
  calls the LLM.
- `worker/run.py`: polls the queue, calls `parse_resume`, marks
  done/failed. Only process that calls the LLM.
- Verified live end-to-end: upload → `pending` row in Supabase → worker
  claims it → LLM call hit the still-exhausted `flash` quota → worker
  correctly marked it `failed` with the error attached. Success path
  (`mark_done`) is code-reviewed but not yet exercised live.

## Next up
1. Once the `gemini-3.5-flash` daily quota resets: re-run `eval/score.py`
   for a confirmed baseline (needs a clean pass — quota is exactly 20
   requests/day, same as corpus size, so any retry exhausts it), and run
   the worker once to verify the `mark_done` success path live.
2. Review and commit step 5 (API + worker).
3. Step 6 — UI (Next.js/Tailwind). Not before step 6 is reached.
