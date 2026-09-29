# Pitch Composer med Chromium til PDF og miniaturer.
#
# Slankt Python-image plus kun Chromium (ikke Microsofts fulde Playwright-image
# med tre browsere, som er over 2 GB og fik Railways image-push til at fejle).
# playwright-versionen SKAL matche requirements.txt, ellers henter pip-pakken
# en anden browser-build end den der installeres her.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

# Afhaengigheder foerst, saa laget caches mellem builds
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt \
    && playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/*

COPY . /app

EXPOSE 8000

# Railway saetter $PORT; lokalt falder vi tilbage til 8000
CMD ["sh", "-c", "cd backend && uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
