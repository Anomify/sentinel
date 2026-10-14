# ── 1. build the dashboard ─────────────────────────────────────────────────────
FROM node:22-slim AS web
WORKDIR /web
COPY web/package*.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

# ── 2. runtime: API + scheduler + headless Chromium for JS-rendered pages ─────
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 SENTINEL_DATA_DIR=/data PORT=8000
WORKDIR /app
COPY pyproject.toml ./
COPY cimonitor/ cimonitor/
RUN pip install --no-cache-dir ".[browser,postgres]" && playwright install --with-deps chromium
COPY config/ config/
COPY --from=web /web/dist web/dist
VOLUME /data
EXPOSE 8000
HEALTHCHECK CMD python -c "import urllib.request;urllib.request.urlopen('http://localhost:8000/api/health')"
CMD ["sentinel", "serve"]
