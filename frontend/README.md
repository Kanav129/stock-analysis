# Frontend

React + TypeScript + Vite dashboard for the stock analysis API.

## Local

```bash
cp .env.example .env   # leave VITE_API_BASE_URL empty
npm install
npm run dev
```

Dev server: http://localhost:5173 — proxies `/api` to `http://127.0.0.1:8001` (local uvicorn). Docker Compose uses host port **8002** so it does not steal 8001.

## Vercel

- Root Directory: `frontend`
- Env: `VITE_API_BASE_URL=https://<your-render-service>.onrender.com`
