# ==============================================================================
# Dockerfile cho Next-Week Prediction Service (Độc lập)
# ==============================================================================
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PORT=8002

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN groupadd --gid 1001 appgroup && \
    useradd --uid 1001 --gid 1001 --create-home appuser

COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY api/ ./api/
COPY models/ ./models/
COPY data_source/ ./data_source/
COPY config.py main.py ./

RUN mkdir -p /app/output/next_week /app/data/raw && \
    chown -R appuser:appgroup /app

USER appuser

EXPOSE 8002

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:${PORT}/health || exit 1

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8002"]
