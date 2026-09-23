FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 FASTEMBED_CACHE_PATH=/app/model-cache HF_HOME=/app/model-cache/huggingface OCR_MODEL_DIR=/app/model-cache/ocr
WORKDIR /app
COPY pyproject.toml ./
COPY app ./app
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir ".[ocr]"
COPY scripts ./scripts
COPY migrations ./migrations
COPY alembic.ini ./
COPY web ./web
RUN useradd --uid 10001 --create-home appuser && mkdir -p /app/model-cache && chown -R appuser:appuser /app
USER 10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--limit-concurrency", "48"]
