# API-only image for Render (and local docker compose).
# Frontend is deployed separately on Vercel.

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8001

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        git \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --upgrade pip \
    && pip install -r requirements.txt

COPY scripts/setup_kronos.sh ./scripts/setup_kronos.sh
RUN chmod +x ./scripts/setup_kronos.sh \
    && ./scripts/setup_kronos.sh

COPY . .

RUN mkdir -p /app/chroma_db /app/logs

EXPOSE 8001

# Render injects PORT; default 8001 for local runs.
CMD ["sh", "-c", "uvicorn rest_api.main:app --host 0.0.0.0 --port ${PORT:-8001}"]
