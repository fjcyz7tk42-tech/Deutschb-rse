# Hub API (FastAPI) from hub/.
# Dependencies are the exact versions of hub/uv.lock (exported to hub-api.requirements.txt),
# so DuckDB matches the version that wrote the seed.
FROM python:3.13.5-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DB_PATH=data/hub.duckdb

WORKDIR /app
COPY docker/hub-api.requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt

COPY hub/config.yaml /app/config.yaml
COPY hub/data/reference /app/data/reference
COPY hub/backend /app/backend
# Build data/hub.duckdb from the Parquet seed now, so the container starts with a finished database.
RUN python -m backend.seed load

RUN useradd --system --uid 10001 hub && chown -R hub /app
USER hub

EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=5s --start-period=10s --retries=6 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/companies', timeout=4)"

CMD ["uvicorn", "backend.api:app", "--host", "0.0.0.0", "--port", "8000"]
