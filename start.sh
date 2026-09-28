#!/usr/bin/env bash
# start.sh — Lance backend FastAPI + frontend Vite en local.
#
# Un .env dans backend/ peut poser GROQ_API_KEY, RNCP_LLM_API_KEY,
# CINETPAY_API_KEY, SMTP_*. Sans ces clés l'application tourne en mode
# guidé / repli, avec un message adapté à l'écran.
set -e

RED='\033[0;31m'; GRN='\033[0;32m'; YEL='\033[1;33m'; BLU='\033[0;34m'; NC='\033[0m'

echo ""
echo -e "${BLU}╔══════════════════════════════════════════════════╗${NC}"
echo -e "${BLU}║               ONE MOOV — développement           ║${NC}"
echo -e "${BLU}╚══════════════════════════════════════════════════╝${NC}"
echo ""

# ── Vérifie / crée un .env de démonstration ─────────────────────────
if [ ! -f "backend/.env" ]; then
  if [ -f "backend/.env.example" ]; then
    cp backend/.env.example backend/.env
    echo -e "${YEL}⚠  backend/.env créé depuis .env.example — pense à renseigner tes clés.${NC}"
  else
    echo -e "${RED}✗ backend/.env absent et pas d'exemple à copier. On continue en mode démo.${NC}"
  fi
fi

for check in "GROQ_API_KEY:conseiller/chatbot" "RNCP_LLM_API_KEY:vérification RNCP web" "CINETPAY_API_KEY:paiement mobile money" "SMTP_HOST:e-mail de vérification"; do
  cle="${check%%:*}"; nom="${check##*:}"
  if grep -q "^${cle}=." backend/.env 2>/dev/null; then
    echo -e "${GRN}✓ ${cle} présente${NC} — ${nom}"
  else
    echo -e "${YEL}○ ${cle} absente${NC} — ${nom} en mode démo"
  fi
done
echo ""

# ── Backend Python ──────────────────────────────────────────────────
echo -e "${YEL}► Installation backend Python…${NC}"
if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -q --upgrade pip
pip install -q -r backend/requirements.txt
echo -e "${GRN}✓ Backend prêt${NC}"

# ── Frontend Node ───────────────────────────────────────────────────
echo -e "${YEL}► Installation frontend Node.js…${NC}"
pushd frontend > /dev/null
if [ ! -d "node_modules" ]; then
  npm install --silent
fi
popd > /dev/null
echo -e "${GRN}✓ Frontend prêt${NC}"

# ── Peuplement initial ──────────────────────────────────────────────
echo -e "${YEL}► Peuplement initial (formations + base RAG)…${NC}"
pushd backend > /dev/null
python -m scripts.enrichir_formations_web 2>/dev/null || true
python -m scripts.ingerer_rag --sans-embedding 2>/dev/null || true
popd > /dev/null
echo -e "${GRN}✓ Base initiale prête${NC}"

echo ""
echo -e "${GRN}═══════════════════════════════════════════════════${NC}"
echo -e "${GRN}  Backend  → http://localhost:8000                 ${NC}"
echo -e "${GRN}  Frontend → http://localhost:5173  ← OUVRIR      ${NC}"
echo -e "${GRN}  API docs → http://localhost:8000/docs            ${NC}"
echo -e "${GRN}═══════════════════════════════════════════════════${NC}"
echo ""

# ── Serveurs ────────────────────────────────────────────────────────
pushd backend > /dev/null
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload &
BPID=$!
popd > /dev/null

sleep 2

pushd frontend > /dev/null
npm run dev &
FPID=$!
popd > /dev/null

echo -e "${GRN}✓ Serveurs démarrés — Ctrl+C pour arrêter${NC}"
trap "kill $BPID $FPID 2>/dev/null; exit" INT TERM
wait
