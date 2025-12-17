FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

COPY backend /app

RUN pip install --upgrade pip

FROM base AS tests

RUN pip install --no-cache-dir ".[dev]"

ENV BRAIN_BUDDY_ENV=test \
    BRAIN_BUDDY_DATA_DIR=/app/data \
    BRAIN_BUDDY_API_PREFIX=/api

CMD ["pytest"]

FROM base AS runtime

RUN pip install --no-cache-dir .

ENV BRAIN_BUDDY_ENV=production \
    BRAIN_BUDDY_DATA_DIR=/app/data \
    BRAIN_BUDDY_API_PREFIX=/api

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "::", "--port", "8000"]
