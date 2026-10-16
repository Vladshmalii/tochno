#!/usr/bin/env bash
# Викликається з CI на сервері: printf "$TOKEN" | bash deploy.sh <tag> <ghcr-user> <image-prefix>
# Вручну (відкат на попередній образ, логін у ghcr вже є): TAG=<sha> docker compose up -d
set -euo pipefail
cd "$(dirname "$0")"

export TAG="$1" IMAGE_PREFIX="$3"
test -f .env || { echo "$(pwd)/.env is missing (template: deploy/.env.example)" >&2; exit 1; }

docker login ghcr.io -u "$2" --password-stdin
trap 'docker logout ghcr.io >/dev/null' EXIT

docker compose pull
docker compose up -d --remove-orphans
echo "$(date -u +%FT%TZ) $TAG" >> deploy-history.log
docker image prune -f
