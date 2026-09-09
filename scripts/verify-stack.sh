#!/usr/bin/env bash
# Brings the stack up and verifies migrations, the cross-language schema
# contract, and the query API. Safe to re-run.
set -euo pipefail
cd "$(dirname "$0")/.."

[ -f .env ] || { echo "no .env; copy .env.example first" >&2; exit 1; }
API_TOKEN=$(grep '^API_TOKEN=' .env | cut -d= -f2-)

echo "==> starting postgres and api"
docker compose up -d --wait postgres api

echo "==> schema contract (python SQL against the prisma-managed schema)"
docker compose run --rm -T ingest python - < scripts/check_schema_contract.py

echo "==> api health"
curl -fsS http://localhost:4000/health; echo

echo "==> api rejects an unauthenticated request"
code=$(curl -s -o /dev/null -w '%{http_code}' http://localhost:4000/alerts)
[ "$code" = "401" ] || { echo "expected 401, got $code" >&2; exit 1; }
echo "401 as expected"

echo "==> api accepts the configured token"
curl -fsS -H "Authorization: Bearer ${API_TOKEN}" 'http://localhost:4000/alerts?limit=1'; echo

echo
echo "stack verified"
