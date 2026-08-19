# Stock Data Insights Application

Agentic RAG workflows for news and financial data, with a **Personal Stock Analysis Dashboard** — React frontend, watchlist management, and AI buy/hold/sell ratings.

## Features

- **Dashboard**: Portfolio summary, holdings (from DB snapshots), AI ratings (score + tag)
- **Watchlist**: Add/remove tickers; drives daily scraping and analysis
- **Stock detail**: Price charts, rating history, AI reasoning and supporting headlines
- **Research reports**: Multi-section core reports (technicals, fundamentals, news, sentiment, decision)
- **Analysis pipeline**: Manual or scheduled sync → scrape → vector sync → LLM rating
- **Price storage**: Multi-resolution ladder for charts — `1m` (~2d), `15m` (~8d), `30m` (~16d), `1h` (~35d), `1d` (forever); daily sync gap-fills then compacts
- **Live prices**: During US RTH with the desk tab open, on-screen tickers refresh every 5 minutes (`1m` Yahoo backfill for the session)
- **Existing RAG APIs**: News RAG, stock price stats, chart data

## Architecture

```
Vercel (frontend/)  →  Render Docker (FastAPI)  →  Supabase Postgres / MongoDB Atlas / Chroma
                              ↓
                    LangGraph (news, stock, research)
```

Locally you can run the same API image with Docker Compose and the Vite app separately.

## Quick start (local)

### 1. Backend

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
bash scripts/setup_kronos.sh   # fetch Kronos model code (once)
cp .env.example .env   # fill in credentials
uvicorn rest_api.main:app --reload --host 0.0.0.0 --port 8001
```

Or with Docker (API only):

```bash
docker compose up --build
```

Docker publishes the API on **http://localhost:8002** so it does not block local uvicorn on **8001** (what the Vite `/api` proxy uses).

### 2. Frontend

```bash
cd frontend
cp .env.example .env   # leave VITE_API_BASE_URL empty to use the Vite `/api` proxy
npm install
npm run dev
```

Open http://localhost:5173

### Kronos price forecast (deep reports)

Deep reports include a **Kronos-small** 20-day forecast. Requirements:

1. `pip install -r requirements.txt` (includes PyTorch, einops, huggingface_hub)
2. `bash scripts/setup_kronos.sh` (downloads upstream model code into `forecast/kronos_model/`)

First forecast run downloads ~100 MB of weights from Hugging Face. On Apple Silicon, inference uses MPS; otherwise CPU.

**Render free/Starter (512 MB):** set `KRONOS_ENABLED=false` (default in `render.yaml`) so deep reports skip Kronos instead of OOMing. Enable on local or a larger instance (e.g. Render Standard 2 GB). Docker builds still run `setup_kronos.sh` for when you turn it on.

Regenerate a deep report after setup to refresh the Kronos section and chart.

## Deploy

### Backend → Render (Docker, free tier)

1. Push this repo to GitHub.
2. In [Render](https://render.com): **New → Blueprint** and select the repo (`render.yaml`),  
   or **New → Web Service** → connect repo → **Docker** runtime → root `Dockerfile`.
3. Set environment variables from `.env.example` (at minimum Postgres, Mongo, Qwen/DashScope API key, and other API keys you use).
4. Set `CORS_ORIGINS` to your Vercel URL, e.g. `https://your-app.vercel.app`  
   (keep local origins too if you still develop against the hosted API).
5. Keep `AUTO_PIPELINE_ENABLED=false` on free tier.
6. After deploy, confirm `https://<your-service>.onrender.com/health` returns `{"status":"ok"}`.

Notes:

- Free dynos **spin down** after idle; the first request can take ~30–60s.
- Chroma data under `/app/chroma_db` is **ephemeral** on free tier (lost on redeploy/sleep). Re-run sync after wake if needed. Postgres/Mongo should be managed (Supabase / Atlas).
- Keep `AUTO_PIPELINE_ENABLED=false` on free tier. Scheduling is done by **GitHub Actions** (below), which also wakes the dyno.

### Scheduled jobs (GitHub Actions → wakes Render)

Workflows in `.github/workflows/`:

| Workflow | When (HKT) | Cron (UTC) | Endpoint |
|----------|------------|------------|----------|
| `daily-sync.yml` | Tue–Sat 06:00 HKT (skip Sun/Mon = US weekend) | `0 22 * * 1-5` | `POST /cron/sync` |
| `weekly-analysis.yml` | Mondays 06:00 ET | `0 11 * * 1` | wake → holdings → sync → analyze |

**Weekly analysis order:** `IBKR holdings (best effort)` → `prices/news (required)` → `analysis (required)`.

1. `POST /cron/holdings/sync` refreshes stock/ETF positions from IBKR Flex. On failure or timeout the workflow emits a warning and continues with the last saved holdings snapshot.
2. `POST /cron/sync` must complete for the expanded universe before analysis starts.
3. `POST /cron/analyze` runs only when today’s price/news sync is complete.

After the API is live, add these **GitHub repo secrets** (Settings → Secrets → Actions):

| Secret | Value |
|--------|--------|
| `API_BASE_URL` | `https://<your-service>.onrender.com` (no trailing slash) |
| `ADMIN_KEY` | Same as Render `ADMIN_KEY` |

Also set on Render (never commit tokens):

| Variable | Purpose |
|----------|---------|
| `IBKR_FLEX_TOKEN` | Flex Web Service token |
| `IBKR_FLEX_QUERY_ID` | Flex Query ID that includes **Open Positions** |

**One-time Flex Query setup (Account Management → Flex Web Service):** create a Token, then a Flex Query with Open Positions for stocks/ETFs (include quantity, cost basis, mark price, unrealized P&L, % of NAV, currency, conid). Point `IBKR_FLEX_QUERY_ID` at that query. You can also sync manually from the dashboard **Sync holdings** button (`POST /holdings/sync`).

You can also run workflows manually: Actions → workflow → **Run workflow**.

### Frontend → Vercel

1. In [Vercel](https://vercel.com): **Add New Project** → import the repo.
2. Set **Root Directory** to `frontend`.
3. Framework preset: Vite (or leave defaults; `vercel.json` sets build/output).
4. Add env var:
   - `VITE_API_BASE_URL` = `https://<your-service>.onrender.com` (no trailing slash)
5. Deploy. Update Render `CORS_ORIGINS` if the Vercel URL differs from what you set earlier.

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | API info |
| GET | `/health` | Health check (Render) |
| GET | `/universe` | Holdings + watchlist tickers |
| GET/POST/DELETE | `/watchlist` | Manage watchlist |
| GET | `/holdings` | Current holdings snapshot |
| POST | `/holdings/sync` | Sync IBKR Flex Open Positions into holdings |
| POST | `/cron/holdings/sync` | Same as above (scheduler / weekly workflow) |
| GET | `/ratings` | Latest rating per ticker |
| GET | `/ratings/{ticker}` | Rating history |
| POST | `/analysis/run` | Trigger analysis |
| GET/PUT | `/settings` | App settings |
| GET | `/stock/{ticker}/chart` | Price chart data |
| GET | `/news/{ticker}` | News RAG |

## Environment variables

See `.env.example` (API) and `frontend/.env.example` (Vite).

| Variable | Where | Purpose |
|----------|--------|---------|
| `CORS_ORIGINS` | Render | Allowed browser origins (comma-separated) |
| `ADMIN_KEY` | Render (+ GitHub Actions) | Access key for login + cron Bearer auth |
| `IBKR_FLEX_TOKEN` / `IBKR_FLEX_QUERY_ID` | Render | IBKR Flex holdings import (never log the token) |
| `VITE_API_BASE_URL` | Vercel | Render API origin for the SPA |
| `PORT` | Render | Injected automatically |
| `AUTO_PIPELINE_ENABLED` | Render | Prefer `false` on free tier |
| `JOB_QUEUE_CLAIM_DELAY_SECONDS` | Render (`45`) / local (`0`) | Seconds a job must sit queued before this worker may claim it (local preferred) |
| `JOB_LEASE_SECONDS` / `JOB_HEARTBEAT_SECONDS` | Both | Job ownership lease TTL (60) and renew interval (30) |
| `JOB_RECLAIM_INTERVAL_SECONDS` | Both | Idle reclaim cadence for expired leases (default 20) |
| `SYNC_MAX_CONCURRENT` | Render (`1`) / local | Parallel tickers during news/price sync |
| `JOB_MAX_CONCURRENT` | Render (`1`) / local | Parallel LLM analysis jobs |
| `JOB_WORKER_ID` | Optional | Stable worker identity; default `{hostname}-{pid}` |
| `KRONOS_ENABLED` | Render | `false` on free/Starter (512 MB); `true` locally / Standard+ |
| `SYNC_INTERVAL` | Render | Seconds between in-process syncs (default 86400) |
| `ANALYSIS_INTERVAL` | Render | Seconds between in-process analyses (default 604800) |
| `RESEARCH_MODEL` / `ANALYSIS_MODEL` | Render | Qwen models (`qwen3.7-flash`, `qwen3.7-max`, etc.) |
| `OPENAI_EMBEDDING_API_KEY` | Render | Embedding-only API key (do not reuse Qwen Lite chat key) |
| `OPENAI_EMBEDDING_BASE_URL` | Render | Embedding provider origin, e.g. `https://api.openai.com/v1` |
| `OPENAI_EMBEDDING_MODEL` | Render | Embedding model on that provider (`text-embedding-3-small`, …) |
| `API_BASE_URL` | GitHub Actions | Render origin for scheduled cron |

## Testing

```bash
pytest
```

## Design

See `.impeccable.md` for UI design context (dark trading-desk aesthetic).
