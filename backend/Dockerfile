FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends whois ca-certificates \
        tesseract-ocr tesseract-ocr-aze tesseract-ocr-rus tesseract-ocr-tur && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml ./
COPY radar ./radar
COPY alembic ./alembic
COPY alembic.ini ./
RUN pip install . && playwright install --with-deps chromium

RUN useradd -m radar && mkdir -p /data/evidence /data/telegram && chown -R radar /data
USER radar
CMD ["uvicorn", "radar.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
