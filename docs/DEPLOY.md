# Deployment runbook

Not deployed yet (STATUS.md's step 7). This is the plan for when it happens.

**₹0 / $0 only.** Every piece of this uses a permanent free tier — no
paid plan, no VM to provision or account to fight with. Real limitations
(sleep-on-idle, quotas, resource caps) are part of the deal — see
"Free-tier limitations" at the end before relying on this for anything
time-sensitive.

Oracle Cloud's Always Free VM was evaluated earlier as a way to get an
always-on host for the worker, but repeated deployment attempts there
were unreliable in practice, and it's not worth the ongoing account/VM
maintenance burden for this project. **It is not part of the current
deployment architecture** — everything below is Vercel + Render Free +
Supabase Free + Gemini, full stop.

## Architecture

```
Vercel
  │
  ▼
Next.js (web/)
  │
  ▼
Render Free
┌─────────────┐
│   FastAPI   │
│    api/     │
│      +      │
│   Worker    │
│  worker/    │
└──────┬──────┘
       │
  ┌────┴────┐
  ▼         ▼
Supabase   Gemini
Postgres    API
+ Storage
```

### Deployment mapping

| Component | Platform |
|---|---|
| `web/` (Next.js) | Vercel Free |
| `api/` (FastAPI) | Render Free — one Web Service |
| `worker/` (queue poller) | same Render Web Service, second process |
| PostgreSQL | Supabase Free (already provisioned) |
| Resume file storage | Supabase Storage Free — already implemented (`storage.py`, see "Supabase" below) |
| Parsing | Gemini API free tier (already in use) |

No paid domain — use the platform-provided URLs (`*.vercel.app`,
`*.onrender.com`) to start.

### Why `api/` and `worker/` run in one Render service

Render's free tier only has a $0 instance type for **Web Services**.
Background Worker is a separate Render service type with no free
instance type at all — the cheapest one is a paid plan. Since ₹0 is a
hard requirement, the worker can't run as its own Render Background
Worker service; it runs inside the same Web Service process as the API
instead (see the start command below). Nothing in `api/` or `worker/`
changes for this — they're still two independent entry points
(`uv run uvicorn api.main:app ...` and `uv run python -m worker.run`,
both already used as-is by `dev.sh`), just started together by one
shell command instead of two separate hosts.

## Prerequisites

- Supabase project already provisioned: `DATABASE_URL`, `SUPABASE_URL`,
  `SUPABASE_SERVICE_ROLE_KEY`, migrations applied (`uv run python -m
  db.migrate`).
- A Gemini API key.
- A Render account (free) and a Vercel account (free).

## 1. Render — deploy `api/` + `worker/`

Create a new **Web Service** on Render, pointed at this repo.

- **Runtime**: Python. The repo's `.python-version` (`3.12`) is picked
  up automatically.
- **Build Command**:
  ```
  pip install uv && uv sync
  ```
- **Start Command** — runs the worker in the background and the API in
  the foreground, both from the exact entry points `dev.sh` already
  uses locally, adapted only for Render's dynamic `$PORT`:
  ```
  uv run python -m worker.run & uv run uvicorn api.main:app --host 0.0.0.0 --port $PORT
  ```
  Render assigns `$PORT` at runtime and health-checks whatever the
  foreground process binds to — that must be the API, not the worker,
  since the worker never listens on a port.
- **Environment variables** — only what the current code actually
  reads (verified directly against `api/main.py`, `worker/run.py`, and
  `storage.py` via `grep os.environ`; nothing invented):

  | Variable | Required | Notes |
  |---|---|---|
  | `DATABASE_URL` | yes | Supabase connection string |
  | `SUPABASE_URL` | yes | |
  | `SUPABASE_SERVICE_ROLE_KEY` | yes | server-side only, see "Supabase" below |
  | `GEMINI_API_KEY` | yes | only the worker calls Gemini — the API never does, it only enqueues |
  | `CORS_ORIGINS` | recommended | set to the Vercel frontend's exact origin once deployed, e.g. `https://your-app.vercel.app` — defaults to `http://localhost:3000` if unset, which is wrong in production |
  | `MAX_RESUME_SIZE_MB` | no | default `5` |
  | `MAX_ATTEMPTS` | no | default `3` |
  | `PROCESSING_TIMEOUT_SECONDS` | no | default `600` |
  | `WORKER_CONCURRENCY` | no | default `1` — start here; Render Free's shared CPU and Gemini's free-tier rate limits are the real ceiling, not this number |
  | `API_DB_POOL_MAX_SIZE` | no | default `5` |
  | `POLL_INTERVAL_SECONDS` | no | default `2` |
  | `WORKER_HEARTBEAT_STALE_SECONDS` | no | default `120` |

## 2. Supabase

Already provisioned. Both the Postgres queue and Storage-backed file
handling are already implemented in this repo, not something the
deployment needs to add:
- PostgreSQL holds job metadata, status, and parsed results
  (`db/jobs.py`).
- Resume file uploads already go to Supabase Storage, not Postgres
  (`storage.py`'s `upload_resume`/`download_resume`, using the
  `resumes` bucket) — confirmed by reading the actual implementation,
  not assumed.
- Security boundary: `DATABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` are
  read only by server-side Python (`api/main.py`, `worker/run.py`,
  `db/migrate.py`), set as Render environment variables, and never
  exposed as `NEXT_PUBLIC_*` values. The Vercel-deployed frontend never
  receives them or the Gemini key — it only ever talks to the Render
  API over HTTP (confirmed: zero references to any of these
  credentials anywhere under `web/`).

## 3. Run migrations

`db/migrate.py` just needs network access to `DATABASE_URL` — it
doesn't need to run on Render at all. Run it from your own machine
against the same Supabase database:
```bash
uv run python -m db.migrate
```
Re-run it the same way after any future migration is added.

## 4. Vercel — deploy `web/`

This is a monorepo — the frontend isn't at the repo root.

- Create a new Vercel project from this repo, set **Root Directory** to
  `web`. Framework preset (Next.js) and build command (`next build`)
  are auto-detected.
- **Environment variable** (verified against `web/src/app/page.tsx`,
  which reads it via `process.env.NEXT_PUBLIC_API_URL`):
  ```
  NEXT_PUBLIC_API_URL=https://<your-render-service>.onrender.com
  ```
  `NEXT_PUBLIC_*` values are inlined at build time, so redeploy after
  setting or changing it.
- `NEXT_PUBLIC_POLL_INTERVAL_MS` is optional (defaults to `2000` in
  `page.tsx` if unset).
- Nothing else needs to be set here — the frontend has no other env
  reads, and in particular never sees `GEMINI_API_KEY`, `DATABASE_URL`,
  or `SUPABASE_SERVICE_ROLE_KEY`.

## 5. Verify

Health/metrics routes actually exist in `api/main.py` — confirmed via
`grep -n "@app\." api/main.py`, not assumed:
```bash
curl https://<your-render-service>.onrender.com/health
curl https://<your-render-service>.onrender.com/health/worker
curl https://<your-render-service>.onrender.com/metrics
```
The first request after a period of inactivity will be slow (see
below) — expected, not a failure. Then do one real upload through the
deployed frontend and confirm it reaches `done`.

## Free-tier limitations

This is a ₹0 deployment. It is not a guarantee of 24/7 uptime or
unlimited traffic — expect and plan around:

- **Render Free spins the service down after ~15 minutes with no
  incoming HTTP traffic**, and the next request wakes it with a cold
  start (can take tens of seconds). Because the worker runs inside that
  same process, the worker is also asleep whenever the service is
  asleep — a job sitting in the queue won't be picked up until some
  HTTP request (an upload, a status poll, a health check) wakes the
  service back up. In practice, the frontend's own status polling
  (`GET /resumes/{id}` every 2s) tends to keep an in-progress job's
  service instance awake until that job finishes, but a resume uploaded
  while nothing else is happening may sit pending for the cold-start
  delay before processing even starts.
- Render Free also caps monthly instance hours and gives the service
  limited, shared CPU/RAM — fine for a low-volume personal project, not
  for real concurrent load.
- **Gemini's free tier has real quotas — both a per-minute and a
  per-day request limit — and processing is not unlimited.** Both were
  hit empirically during this project's own testing (a 5 RPM burst
  limit and a 20-request/day cap; see `docs/STATUS.md`). Bursts of
  uploads queue and retry with backoff rather than failing outright
  (`worker/run.py`), but enough volume in one day will hit the daily
  cap outright regardless of retries — do not size expectations around
  unlimited resume processing.
- Supabase Free caps database storage, file storage, and concurrent
  connections. The API and worker already pool connections
  conservatively for this reason (`API_DB_POOL_MAX_SIZE`,
  `WORKER_CONCURRENCY`).

## Not covered here

- Automated deploys (Render and Vercel both auto-deploy on push once
  connected to the repo, so this mostly happens for free already — a
  custom CI pipeline isn't needed to get that).
- Log aggregation beyond Render's built-in log viewer — the
  `/health`, `/health/worker`, and `/metrics` endpoints (`docs/STATUS.md`)
  cover the operational questions that matter most for a project this
  size; a dedicated log shipper isn't justified yet.
