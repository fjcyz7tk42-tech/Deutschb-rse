# Hub API (FastAPI) from the team repo futury_4_2026, passed in as the build context "hub".
# Dependencies are the exact versions of futury_4_2026/uv.lock (exported to hub-api.requirements.txt),
# so DuckDB matches the version that wrote data/hub.duckdb.
FROM python:3.13.5-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DB_PATH=data/hub.duckdb

WORKDIR /app
COPY docker/hub-api.requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt

# Code only. data/ (database, reference CSVs) and config.yaml are mounted read-only at runtime.
COPY --from=hub backend /app/backend

RUN useradd --system --uid 10001 hub && chown -R hub /app
USER hub

EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=5s --start-period=10s --retries=6 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/companies', timeout=4)"

CMD ["uvicorn", "backend.api:app", "--host", "0.0.0.0", "--port", "8000"]
