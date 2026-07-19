# Frontend

React + TypeScript + Vite dashboard for the stock analysis API.

## Local

```bash
cp .env.example .env   # leave VITE_API_BASE_URL empty
npm install
npm run dev
```

Dev server: http://localhost:5173 — proxies `/api` to `http://localhost:8001`.

## Vercel

- Root Directory: `frontend`
- Env: `VITE_API_BASE_URL=https://<your-render-service>.onrender.com`
