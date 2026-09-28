FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Dépendances système minimales pour psycopg2
RUN apt-get update && apt-get install -y --no-install-recommends \
      libpq5 curl && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Embeddings : décommenter pour activer la recherche sémantique.
# L'image grossit fortement (torch), d'où le choix de les rendre optionnels.
# COPY requirements-embeddings.txt .
# RUN pip install --no-cache-dir -r requirements-embeddings.txt

COPY . .

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD curl -fsS http://localhost:8000/api/sante || exit 1

CMD ["sh", "-c", "python -m scripts.migrer && python -m scripts.ingerer_rag && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
