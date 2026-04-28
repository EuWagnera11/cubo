#!/usr/bin/env bash
# deploy.sh — script de deploy/update no VPS
# Uso: ./deploy.sh

set -euo pipefail

cd "$(dirname "$0")"

echo "🔄 git pull..."
git pull origin main

echo "🐳 rebuild + restart api..."
docker compose up -d --build api

echo "🩺 aguardando health check..."
for i in {1..30}; do
    if docker compose exec -T api curl -fsS http://localhost:8000/health > /dev/null 2>&1; then
        echo "✅ API healthy!"
        break
    fi
    echo "  ($i/30) ainda subindo..."
    sleep 2
done

echo "📊 status:"
docker compose ps

echo "📜 últimas 30 linhas de log:"
docker compose logs --tail=30 api

echo "🎉 deploy concluído"
