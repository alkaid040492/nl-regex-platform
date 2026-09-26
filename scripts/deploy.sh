#!/usr/bin/env bash
# (Re)deploy the production stack on the server. Safe to re-run; pulls latest main, rebuilds, restarts.
set -euo pipefail
DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$DIR"

[ -f .env ] || { echo "missing $DIR/.env (copy from .env.example and fill in)"; exit 1; }
for v in OPENROUTER_API_KEY FERNET_KEY DJANGO_SECRET_KEY DOMAIN; do
  grep -qE "^$v=.+" .env && ! grep -qE "^$v=(REPLACE_ME|change-me|sk-or-v1-\.\.\.|you@example.com)" .env \
    || { echo ".env: $v is not set"; exit 1; }
done

git pull --ff-only
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build --remove-orphans
docker image prune -f >/dev/null

echo ">> waiting for API"
for i in $(seq 1 30); do
  if docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T web curl -fsS http://localhost:8000/api/health/ >/dev/null 2>&1; then
    echo "healthy"; break
  fi
  sleep 5
done
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps
echo
echo "Open https://$(grep -E '^DOMAIN=' .env | cut -d= -f2)"
