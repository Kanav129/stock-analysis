# Stock Data Insights Application

Agentic RAG workflows for news and financial data, with a **Personal Stock Analysis Dashboard** — React frontend, watchlist management, and AI buy/hold/sell ratings.

## Features

- **Dashboard**: Portfolio summary, holdings (from DB snapshots), AI ratings (score + tag)
- **Watchlist**: Add/remove tickers; drives daily scraping and analysis
- **Stock detail**: Price charts, rating history, AI reasoning and supporting headlines
- **Research reports**: Multi-section core reports (technicals, fundamentals, news, sentiment, decision)
- **Analysis pipeline**: Manual or scheduled sync → scrape → vector sync → LLM rating
- **Price storage**: Daily closes retained long-term; last 30 days also keep 5‑minute bars (upsert, no duplicates)
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
cp .env.example .env   # fill in credentials
uvicorn rest_api.main:app --reload --host 0.0.0.0 --port 8001
```

Or with Docker (API only):

```bash
docker compose up --build
```

### 2. Frontend

```bash
cd frontend
cp .env.example .env   # leave VITE_API_BASE_URL empty to use the Vite `/api` proxy
npm install
npm run dev
```

Open http://localhost:5173

## Deploy

### Backend → Render (Docker, free tier)

1. Push this repo to GitHub.
2. In [Render](https://render.com): **New → Blueprint** and select the repo (`render.yaml`),  
   or **New → Web Service** → connect repo → **Docker** runtime → root `Dockerfile`.
3. Set environment variables from `.env.example` (at minimum Postgres, Mongo, OpenRouter, and API keys you use).
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
| `daily-sync.yml` | Every day 09:00 | `0 1 * * *` | `POST /cron/sync` |
| `weekly-analysis.yml` | Saturdays 09:30 | `30 1 * * 6` | `POST /cron/analyze` |

After the API is live, add these **GitHub repo secrets** (Settings → Secrets → Actions):

| Secret | Value |
|--------|--------|
| `API_BASE_URL` | `https://<your-service>.onrender.com` (no trailing slash) |
| `ADMIN_KEY` | Same as Render `ADMIN_KEY` |

You can also run them manually: Actions → workflow → **Run workflow**.

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
| `VITE_API_BASE_URL` | Vercel | Render API origin for the SPA |
| `PORT` | Render | Injected automatically |
| `AUTO_PIPELINE_ENABLED` | Render | Prefer `false` on free tier |
| `SYNC_INTERVAL` | Render | Seconds between in-process syncs (default 86400) |
| `ANALYSIS_INTERVAL` | Render | Seconds between in-process analyses (default 604800) |
| `RESEARCH_MODEL` / `ANALYSIS_MODEL` | Render | OpenRouter models |
| `API_BASE_URL` | GitHub Actions | Render origin for scheduled cron |

## Testing

```bash
pytest
```

## Design

See `.impeccable.md` for UI design context (dark trading-desk aesthetic).
