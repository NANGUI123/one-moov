#!/usr/bin/env bash
# Installe ou met à jour l'API One Moov sur un VPS Ubuntu/Debian.
#   1re fois  : curl -fsSL https://raw.githubusercontent.com/NANGUI123/one-moov/claude/app-architecture-rag-integration-1d37vb/deploy/install.sh | sudo bash
#   Mise à jour : sudo bash /opt/one-moov/deploy/install.sh
set -euo pipefail

DEPOT="https://github.com/NANGUI123/one-moov.git"
BRANCHE="${BRANCHE:-claude/app-architecture-rag-integration-1d37vb}"
DOSSIER="/opt/one-moov"

if [ "$(id -u)" -ne 0 ]; then
  echo "Lance ce script avec sudo."
  exit 1
fi

if ! command -v git >/dev/null 2>&1; then
  apt-get update -qq && apt-get install -y -qq git
fi
if ! command -v docker >/dev/null 2>&1; then
  echo "► Installation de Docker…"
  curl -fsSL https://get.docker.com | sh
fi

if [ -d "$DOSSIER/.git" ]; then
  echo "► Mise à jour du code ($BRANCHE)…"
  git -C "$DOSSIER" fetch --quiet origin "$BRANCHE"
  git -C "$DOSSIER" checkout --quiet -B "$BRANCHE" "origin/$BRANCHE"
else
  echo "► Récupération du code ($BRANCHE)…"
  git clone --quiet --branch "$BRANCHE" "$DEPOT" "$DOSSIER"
fi

cd "$DOSSIER/deploy"

if [ ! -f .env ]; then
  cp .env.example .env
  sed -i "s/^POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=$(openssl rand -hex 24)/" .env
  sed -i "s/^JWT_SECRET=.*/JWT_SECRET=$(openssl rand -hex 32)/" .env
  chmod 600 .env
  echo ""
  echo "✓ $DOSSIER/deploy/.env créé (mot de passe base et JWT générés)."
  echo "  1. Renseigne tes clés :   nano $DOSSIER/deploy/.env"
  echo "  2. Relance le script :    sudo bash $DOSSIER/deploy/install.sh"
  exit 0
fi

echo "► Construction et démarrage (2 à 4 min la première fois)…"
docker compose up -d --build --remove-orphans
docker image prune -f >/dev/null

DOMAINE="$(grep -E '^API_DOMAIN=' .env | cut -d= -f2)"
echo "► Attente de l'API…"
for _ in $(seq 1 60); do
  if docker compose exec -T api python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)" >/dev/null 2>&1; then
    echo "✓ API en ligne. Vérifie depuis ton navigateur : https://$DOMAINE/health"
    exit 0
  fi
  sleep 5
done

echo "✗ L'API ne répond pas après 5 min. Journaux :"
echo "  cd $DOSSIER/deploy && docker compose logs --tail=100 api"
exit 1
