# Pitch Composer med Chromium til PDF og miniaturer.
#
# Microsofts Playwright-image har Chromium og alle systembiblioteker
# installeret. Tag'et SKAL matche playwright-versionen i requirements.txt,
# ellers leder pip-pakken efter en anden browser-build end den der ligger i
# imaget. Begge er pinnet til 1.63.0.
FROM mcr.microsoft.com/playwright/python:v1.63.0-jammy

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Afhaengigheder foerst, saa laget caches mellem builds
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

COPY . /app

EXPOSE 8000

# Railway saetter $PORT; lokalt falder vi tilbage til 8000
CMD ["sh", "-c", "cd backend && uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
