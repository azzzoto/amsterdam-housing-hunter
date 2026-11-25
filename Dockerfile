FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY pyproject.toml requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY config ./config
COPY migrations ./migrations
COPY scripts ./scripts
RUN mkdir -p /app/data /app/backups && useradd --system --uid 10001 --create-home appuser \
    && chown -R appuser:appuser /app
USER appuser

HEALTHCHECK --interval=60s --timeout=10s --start-period=20s --retries=3 \
    CMD ["python", "-m", "app.main", "--healthcheck"]

CMD ["python", "-m", "app.main"]
