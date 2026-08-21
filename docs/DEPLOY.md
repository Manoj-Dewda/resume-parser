# Deployment runbook

Not deployed yet (STATUS.md's step 7). This is the plan for when it happens.

**₹0 / $0 only.** Every piece of this uses a permanent free tier — no
paid plan. Real limitations (spin-down, quotas, resource caps) are part
of the deal — see "Free-tier limitations" at the end before relying on
this for anything time-sensitive.

## Architecture

```
User
 ↓
Vercel — Next.js frontend (web/)
 ↓ HTTPS
Render Free — FastAPI only (api/)
 ↕
Supabase PostgreSQL — job queue, status, parsed results
 ↕
Google Cloud Always Free e2-micro VM — Worker only (worker/), always-on
 ↓
Supabase Storage — raw resume files
 ↓
Gemini API — parsing
```

### Deployment mapping

| Component | Platform |
|---|---|
| `web/` (Next.js) | Vercel Free |
| `api/` (FastAPI) | Render Free — Web Service |
| `worker/` (queue poller) | Google Cloud Always Free — e2-micro VM |
| PostgreSQL | Supabase Free (already provisioned) |
| Resume file storage | Supabase Storage Free (already provisioned) |
| Parsing | Gemini API free tier (already in use) |

No paid domain — use the platform-provided URLs (`*.vercel.app`,
`*.onrender.com`) plus the VM's IP for SSH.

### Why the API and the worker are split across two hosts

Render Free's Web Service is the only $0 Render instance type, and it
sleeps after ~15 minutes with no inbound HTTP traffic, waking on the
next request (tens of seconds of cold start). That's an acceptable
trade for `api/`: it's a request/response service, so an occasional
cold start on an incoming request is a one-time delay for whoever
triggered it.

It is **not** acceptable for `worker/`: it's a `while True` loop that
continuously polls the queue and calls Gemini (`worker/run.py`). A
sleeping worker means queued jobs simply don't get processed until
something else happens to send the Render service an HTTP request —
production correctness would depend on incidental traffic, which isn't
a real guarantee. So the worker gets its own host that never sleeps:
Google Cloud's Always Free tier includes one `e2-micro` VM per billing
account, in specific regions, indefinitely (not a time-limited trial
credit) — small, but the worker is lightweight (poll, download, call
Gemini, write a status back) and doesn't need to serve traffic, so it
fits.

This means `api/` and `worker/` are deployed independently even though
nothing changes in either module — they're already two separate entry
points (`uv run uvicorn api.main:app ...` vs. `uv run python -m
worker.run`), just run on two different hosts instead of one.

**Render Free is still a reasonable choice for development/demo use of
the full stack** (API + worker together, sleep-and-all) — just not what
this plan uses for the worker in what's meant to run continuously.

## Prerequisites

- Supabase project already provisioned: `DATABASE_URL`, `SUPABASE_URL`,
  `SUPABASE_SERVICE_ROLE_KEY`, migrations applied (`uv run python -m
  db.migrate`).
- A Gemini API key.
- A Render account (free) and a Vercel account (free).
- A Google Cloud account. Always Free still requires billing/card
  verification at signup, even though the `e2-micro` shape itself won't
  be charged as long as usage stays inside the Always Free allocation
  (one instance, an eligible region, within the free disk/egress caps).

## 1. Google Cloud — deploy `worker/`

1. Create a VM instance on the `e2-micro` machine type, in one of the
   Always Free–eligible regions: `us-west1`, `us-central1`, or
   `us-east1`. Any other machine type or region starts billing
   immediately — double-check both before creating it.
2. No inbound firewall changes are needed. The worker only makes
   outbound connections (to Supabase and Gemini) — it doesn't listen on
   a port, so there's nothing to expose and no TLS/domain requirement
   here at all. SSH access (port 22) is enabled by GCP's default network
   rules already.
3. On the VM:
   ```bash
   sudo apt update && sudo apt install -y git
   curl -LsSf https://astral.sh/uv/install.sh | sh   # installs uv

   git clone <your-repo-url> resume-parser
   cd resume-parser
   uv sync

   cp .env.example .env
   # Fill in real values — see the table below.
   ```

   Environment variables — only what `worker/run.py` (and the
   `storage.py` it also calls into) actually reads:

   | Variable | Required | Notes |
   |---|---|---|
   | `GEMINI_API_KEY` | yes | only the worker calls Gemini |
   | `DATABASE_URL` | yes | Supabase connection string |
   | `SUPABASE_URL` | yes | |
   | `SUPABASE_SERVICE_ROLE_KEY` | yes | server-side only — see "Supabase" below |
   | `WORKER_CONCURRENCY` | no | default `1` — keep low on an `e2-micro`'s single shared core |
   | `MAX_ATTEMPTS` | no | default `3` |
   | `PROCESSING_TIMEOUT_SECONDS` | no | default `600` |
   | `POLL_INTERVAL_SECONDS` | no | default `2` |

   `CORS_ORIGINS`, `MAX_RESUME_SIZE_MB`, `API_DB_POOL_MAX_SIZE`, and
   `WORKER_HEARTBEAT_STALE_SECONDS` are `api/`-only — no need to set
   them here.
4. Run it as a systemd service so it survives reboots and restarts on
   crash:
   ```ini
   # /etc/systemd/system/resume-parser-worker.service
   [Unit]
   Description=Resume Parser Worker
   After=network.target

   [Service]
   User=<your-vm-user>
   WorkingDirectory=/home/<your-vm-user>/resume-parser
   EnvironmentFile=/home/<your-vm-user>/resume-parser/.env
   ExecStart=/home/<your-vm-user>/.local/bin/uv run python -m worker.run
   Restart=on-failure
   RestartSec=5

   [Install]
   WantedBy=multi-user.target
   ```
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable --now resume-parser-worker
   ```

## 2. Render — deploy `api/`

Create a new **Web Service** on Render, pointed at this repo.

- **Runtime**: Python. The repo's `.python-version` (`3.12`) is picked up
  automatically.
- **Build Command**: `pip install uv && uv sync`
- **Start Command**: `uv run uvicorn api.main:app --host 0.0.0.0 --port $PORT`
  — the same entry point `dev.sh` uses locally, adapted only for
  Render's dynamic `$PORT`. No worker process runs here.
- **Environment variables** — only what `api/main.py` (and the
  `storage.py` it calls into) actually reads:

  | Variable | Required | Notes |
  |---|---|---|
  | `DATABASE_URL` | yes | Supabase connection string |
  | `SUPABASE_URL` | yes | |
  | `SUPABASE_SERVICE_ROLE_KEY` | yes | server-side only — see "Supabase" below |
  | `CORS_ORIGINS` | recommended | set to the Vercel frontend's exact origin once deployed, e.g. `https://your-app.vercel.app` — defaults to `http://localhost:3000` if unset, which is wrong in production |
  | `MAX_RESUME_SIZE_MB` | no | default `5` |
  | `API_DB_POOL_MAX_SIZE` | no | default `5` |
  | `WORKER_HEARTBEAT_STALE_SECONDS` | no | default `120` |

  `GEMINI_API_KEY` is **not** needed here — the API never calls Gemini
  directly (it only enqueues); only the worker does.

## 3. Supabase

Already provisioned. Security boundary worth stating explicitly given
the split above: `DATABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` are set
as environment variables on Render and on the GCP VM only — never as
`NEXT_PUBLIC_*` values. The Vercel-deployed frontend never receives
them; it only ever talks to the Render API over HTTP (confirmed earlier
in this project: zero references to either credential anywhere under
`web/`).

## 4. Run migrations

`db/migrate.py` just needs network access to `DATABASE_URL` — it can run
from any machine, not specifically Render or the GCP VM. Run it from
your own machine against the same Supabase database:
```bash
uv run python -m db.migrate
```
Re-run it the same way after any future migration is added.

## 5. Vercel — deploy `web/`

This is a monorepo — the frontend isn't at the repo root.

- Create a new Vercel project from this repo, set **Root Directory** to
  `web`. Framework preset (Next.js) and build command (`next build`)
  are auto-detected.
- **Environment variable**:
  ```
  NEXT_PUBLIC_API_URL=https://<your-render-service>.onrender.com
  ```
  `NEXT_PUBLIC_*` values are inlined at build time (`web/src/app/page.tsx`
  reads it via `process.env.NEXT_PUBLIC_API_URL`), so redeploy after
  setting or changing it.
- `NEXT_PUBLIC_POLL_INTERVAL_MS` is optional (defaults to `2000` in
  `page.tsx` if unset).

## 6. Connect the pieces

Set `CORS_ORIGINS` on the Render service to the Vercel deployment's exact
origin (`api/main.py` parses it as a comma-separated allowlist — no
wildcard). Both Vercel and Render serve HTTPS by default, so there's no
mixed-content issue between them.

## 7. Verify

```bash
curl https://<your-render-service>.onrender.com/health
curl https://<your-render-service>.onrender.com/health/worker
curl https://<your-render-service>.onrender.com/metrics
```
`/health/worker` depends on the GCP VM's worker actually running and
having written a heartbeat — check that before assuming a failure here
is Render's fault. The first API request after inactivity will be slow
(cold start) — expected, not a failure. Then do one real upload through
the deployed frontend and confirm it reaches `done`.

## Free-tier limitations

This is a ₹0 deployment, not a guarantee of 24/7 uptime or unlimited
traffic. Expect and plan around:

- **Render Free spins `api/` down after ~15 minutes of inactivity**,
  cold-starting (tens of seconds) on the next request. This only
  affects request latency now that the worker lives elsewhere — it no
  longer stalls job processing.
- Google Cloud's Always Free `e2-micro` is a genuinely small,
  shared-core, 1 GB RAM instance — fine for a lightweight poll-and-call
  loop at low volume, not for heavy concurrency (`WORKER_CONCURRENCY`
  should stay low here regardless of what Gemini's own rate limits
  allow).
- Gemini's free tier has both a per-minute and a per-day request quota
  (empirically hit both during this project's own testing — see
  `docs/STATUS.md`). Bursts of uploads will queue and retry rather than
  fail outright (`worker/run.py`'s backoff/retry logic), but won't all
  complete quickly.
- Supabase Free caps database storage, file storage, and concurrent
  connections. The API and worker already pool connections conservatively
  for this reason (`API_DB_POOL_MAX_SIZE`, `WORKER_CONCURRENCY`).

## Not covered here

- Automated deploys — Render and Vercel both auto-deploy on push once
  connected to the repo, so `api/` and `web/` mostly get this for free
  already. The GCP VM does not auto-deploy; picking up a code change
  there means `git pull && uv sync && sudo systemctl restart
  resume-parser-worker` by hand, or a small CI job to do that over SSH —
  not built yet.
- Log aggregation beyond Render's log viewer and the VM's `journalctl -u
  resume-parser-worker` — the `/health`, `/health/worker`, and
  `/metrics` endpoints (`docs/STATUS.md`) cover the operational
  questions that matter most for a project this size; a dedicated log
  shipper isn't justified yet.
