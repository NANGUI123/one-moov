#!/bin/sh
# Relance l'API en développement, détachée du terminal.
#
# Ce script ne pose AUCUNE variable de configuration, et c'est délibéré.
#
# Il en posait deux avant — LLM_PROVIDER=mock et EMBEDDINGS_ENABLED=false —
# avec l'intention louable d'offrir des valeurs sûres par défaut. Sauf que
# pydantic-settings fait primer l'environnement sur le fichier .env. Les clés
# soigneusement posées dans .env étaient donc ignorées, l'application
# répondait en mode guidé, et rien n'expliquait pourquoi : .env disait groq,
# /api/sante disait mock.
#
# Les valeurs par défaut vivent dans app/config.py, où elles ont leur place.
# Ce script se contente de lancer le serveur.
#
# Pour forcer une valeur le temps d'un lancement, elle se donne en ligne :
#   LLM_PROVIDER=mock ./lancer_dev.sh
# Là c'est une intention explicite, pas une surprise.

cd "$(dirname "$0")" || exit 1

pkill -f "uvicorn app.main" 2>/dev/null
sleep 2

setsid nohup python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8000 \
  > "${JOURNAL:-/tmp/onemoov-api.log}" 2>&1 < /dev/null &

sleep 8
curl -s -o /dev/null -w "API %{http_code}\n" http://127.0.0.1:8000/api/sante
