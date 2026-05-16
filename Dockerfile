# syntax=docker/dockerfile:1
FROM node:22-alpine AS frontend
WORKDIR /build/web
COPY web/package.json ./
RUN npm install
COPY web/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --no-dev
COPY --from=frontend /build/src/jgi/web/static ./src/jgi/web/static

ENV REPORTS_DIR=/data/reports
ENV CACHE_DIR=/data/cache
EXPOSE 8080

CMD ["uv", "run", "jgi-serve"]
