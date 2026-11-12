# Live feed service (live/ in this repo). Reuses the team fetcher's EQS categories, title rules and the
# tagesschau name list from hub/backend.
FROM python:3.13.5-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app \
    LIVE_DATA_DIR=/app/live-data

WORKDIR /app
COPY docker/hub-api.requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt

COPY hub/backend /app/backend
COPY live /app/live

RUN useradd --system --uid 10001 hub && mkdir -p /app/live-data && chown -R hub /app
USER hub

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=4 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/status', timeout=4)"

CMD ["uvicorn", "live.app:app", "--host", "0.0.0.0", "--port", "8000"]
