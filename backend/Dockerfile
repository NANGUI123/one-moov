# Image de production de l'API One Moov.
# Python 3.11 : pydantic 2.8, python-jose et bcrypt cassent sur 3.13.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
RUN useradd --create-home --uid 1000 onemoov && chown -R onemoov /app
USER onemoov

EXPOSE 8000
CMD ["sh", "-c", "python -m scripts.enrichir_formations_web || true; python -m scripts.ingerer_rag --sans-embedding || true; exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips '*'"]
