# discord-message-resender task runner. Run `just` to list recipes.
# Recipes assume the repository root as the working directory.

# Show all recipes
default:
    @just --list

# ── Setup ─────────────────────────────────────────────────────────

# Create .env and routes.yaml from examples, then install everything
[group('setup')]
setup: install
    [ -f .env ] || cp .env.example .env
    [ -f config/routes.yaml ] || cp config/routes.example.yaml config/routes.yaml
    @echo ""
    @echo "Next: edit .env (token, webhooks, API_TOKEN) and config/routes.yaml,"
    @echo "then run:  just check-token && just up"

# Install both toolchains' dependencies
[group('setup')]
install: install-api install-ingest

# Install the API (pnpm) dependencies and generate the Prisma client
[group('setup')]
install-api:
    cd api && pnpm install && pnpm db:generate

# Install the ingest (uv) dependencies
[group('setup')]
install-ingest:
    cd ingest && uv sync

# ── Quality gates ─────────────────────────────────────────────────

# Everything CI runs locally: lint, typecheck, build, tests
[group('check')]
check: lint typecheck build test

# Lint both services
[group('check')]
lint: lint-api lint-ingest

[group('check')]
lint-api:
    cd api && pnpm lint

[group('check')]
lint-ingest:
    cd ingest && uv run ruff check . && uv run ruff format --check .

# Auto-fix lint and formatting in both services
[group('check')]
fix:
    cd api && pnpm lint:fix
    cd ingest && uv run ruff check --fix . && uv run ruff format .

# Typecheck the API (TypeScript)
[group('check')]
typecheck:
    cd api && pnpm typecheck

# Build the API
[group('check')]
build:
    cd api && pnpm build

# Run the ingest test suite (the API is covered by typecheck, build, and integration)
[group('check')]
test:
    cd ingest && uv run pytest

# ── Database (Prisma) ─────────────────────────────────────────────

# Regenerate the Prisma client
[group('db')]
db-generate:
    cd api && pnpm db:generate

# Create and apply a new migration from schema changes (interactive)
[group('db')]
db-migrate:
    cd api && pnpm db:migrate

# Apply pending migrations without creating one
[group('db')]
db-deploy:
    cd api && pnpm db:deploy

# Open Prisma Studio against the database
[group('db')]
db-studio:
    cd api && pnpm db:studio

# ── Docker stack ──────────────────────────────────────────────────

# Start the stack in the background
[group('docker')]
up:
    docker compose up -d

# Stop the stack, keeping the archive
[group('docker')]
down:
    docker compose down

# Follow a service's logs (default: ingest)
[group('docker')]
logs service="ingest":
    docker compose logs -f {{ service }}

# Show service status
[group('docker')]
ps:
    docker compose ps

# Rebuild both images
[group('docker')]
build-images:
    docker compose build

# Rebuild images and restart the stack
[group('docker')]
rebuild: build-images
    docker compose up -d

# ── Verify / operate ──────────────────────────────────────────────

# Validate the Discord token in .env (read-only call to /users/@me)
[group('verify')]
check-token:
    cd ingest && uv run resender-check-token

# Bring the stack up and verify migrations, the schema contract, and auth
[group('verify')]
verify:
    ./scripts/verify-stack.sh

# Run the cross-language schema contract check (needs the stack up)
[group('verify')]
check-contract:
    docker compose run --rm -T ingest python - < scripts/check_schema_contract.py

# Run the delivery retry lifecycle check (needs the stack up)
[group('verify')]
check-retry:
    docker compose run --rm -T ingest python - < scripts/check_retry_lifecycle.py

# Both live-Postgres integration checks
[group('verify')]
check-integration: check-contract check-retry
