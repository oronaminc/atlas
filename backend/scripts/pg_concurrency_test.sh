#!/usr/bin/env bash
# Runs the real-PostgreSQL concurrency tests (tests/pg) against the
# docker-compose postgres. Usage: ./scripts/pg_concurrency_test.sh
set -euo pipefail
cd "$(dirname "$0")/.."

docker compose -f ../docker-compose.yml up -d postgres
echo "waiting for postgres..."
for _ in $(seq 1 30); do
  docker compose -f ../docker-compose.yml exec -T postgres pg_isready -U atlas >/dev/null 2>&1 && break
  sleep 1
done

export ATLAS_PG_TEST_URL="postgresql+asyncpg://atlas:atlas@localhost:5432/atlas"
uv run pytest tests/pg -v
