# Vercel + Render deployment design

Approved 2026-07-19.

## Summary

- **Frontend**: Vite React app on Vercel (`frontend/` root).
- **Backend**: FastAPI API-only Docker image on Render free tier.
- **Data**: Supabase Postgres + MongoDB Atlas; Chroma on container disk (ephemeral on free tier).

## Key config

- `CORS_ORIGINS` on API for Vercel (+ local Vite).
- `VITE_API_BASE_URL` on Vercel pointing at Render origin.
- Local Vite keeps `/api` proxy when `VITE_API_BASE_URL` is unset.
- `AUTO_PIPELINE_ENABLED=false` recommended on Render free.

## Docker

- Single API `Dockerfile` (no nginx/frontend bundle).
- `docker-compose.yml` runs the API locally on port 8001.
