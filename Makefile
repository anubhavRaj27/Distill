# Distill.
#
# The commands the README spells out, in one place, so that "how do I run this" has one
# answer. `docs/implementation.md` section 10 planned `make setup` and `make dev`; this is
# those, plus what deployment turned out to need.
#
# Run `make` on its own for the list.

SHELL := /bin/bash
.DEFAULT_GOAL := help

SERVER := server
CLIENT := client
IMAGE ?= distill
PORT ?= 8000

# The database this repository creates locally. Overridden by DATABASE_URL in the
# environment, which is how you point `make migrate` at a deployed database.
LOCAL_DB_URL ?= postgresql+asyncpg://distill:distill@localhost:5432/distill

.PHONY: help
help: ## List the targets
	@echo "Distill"
	@echo
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[1m%-16s\033[0m %s\n", $$1, $$2}'
	@echo
	@echo "  Deployment lives in docs/deployment.md."

# ---------------------------------------------------------------------------
# Local development
# ---------------------------------------------------------------------------

.PHONY: setup
setup: ## Install everything: Python dependencies, node modules, the database schema
	cd $(SERVER) && uv sync
	cd $(CLIENT) && npm ci
	$(MAKE) db
	$(MAKE) migrate

.PHONY: db
db: ## Create the local Postgres role and database (safe to re-run)
	@psql -d postgres -f $(SERVER)/scripts/bootstrap_db.sql

.PHONY: migrate
migrate: ## Bring the database to head. DATABASE_URL=... to target a deployed one
	cd $(SERVER) && DATABASE_URL="$${DATABASE_URL:-$(LOCAL_DB_URL)}" uv run alembic upgrade head

.PHONY: api
api: ## Run the API on :8000. One worker, always: decisions D9 and D14
	cd $(SERVER) && uv run uvicorn app.main:app --port $(PORT) --workers 1

.PHONY: web
web: ## Run the Vite dev server on :5173, proxying /api to the API
	cd $(CLIENT) && npm run dev

.PHONY: dev
dev: ## What to run: `make api` in one terminal, `make web` in another
	@echo "Two processes, two terminals:"
	@echo "  make api   the backend on :$(PORT)"
	@echo "  make web   the interface on :5173, proxying /api to it"
	@echo
	@echo "Deliberately not backgrounded here. The API's document queue lives in the"
	@echo "process, so you want its log in front of you while documents are being read."

# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

.PHONY: test
test: ## Every test, both sides
	cd $(SERVER) && uv run pytest -q
	cd $(CLIENT) && npm run test -- --run

.PHONY: test-fast
test-fast: ## The server tests that need no database
	cd $(SERVER) && uv run pytest tests/unit -q

.PHONY: lint
lint: ## Ruff and TypeScript
	cd $(SERVER) && uv run ruff check app tests
	cd $(CLIENT) && npx tsc --noEmit

.PHONY: typecheck
typecheck: ## mypy over the server
	cd $(SERVER) && uv run mypy app

.PHONY: check
check: lint test ## Lint and test. What to run before pushing

.PHONY: openapi
openapi: ## Regenerate the OpenAPI document and the client's types from it
	cd $(SERVER) && uv run python -c "from app.main import export_openapi; from pathlib import Path; export_openapi(Path('../client/src/api/openapi.json'))"
	cd $(CLIENT) && npx openapi-typescript src/api/openapi.json -o src/api/schema.d.ts

# ---------------------------------------------------------------------------
# Build and deployment
# ---------------------------------------------------------------------------

.PHONY: build-client
build-client: ## Build the interface into client/dist, which the API then serves
	cd $(CLIENT) && npm run build

.PHONY: serve
serve: build-client ## Run the production shape locally: one process, one origin, no Vite
	cd $(SERVER) && CLIENT_DIST_DIR=../client/dist uv run uvicorn app.main:app --port $(PORT) --workers 1

.PHONY: docker-build
docker-build: ## Build the deployment image from the repository root
	docker build -t $(IMAGE) .

.PHONY: docker-run
docker-run: ## Run that image against server/.env. Needs DATABASE_URL and GEMINI_API_KEY in it
	docker run --rm -it \
		--env-file $(SERVER)/.env \
		-e PORT=$(PORT) \
		-p $(PORT):$(PORT) \
		$(IMAGE)

.PHONY: preflight
preflight: ## The five things that break a deploy, checked before you push one
	@echo "1. lock file matches pyproject"
	@cd $(SERVER) && uv lock --check
	@echo "2. the interface builds"
	@$(MAKE) --no-print-directory build-client >/dev/null
	@test -f $(CLIENT)/dist/index.html && echo "   client/dist/index.html present"
	@echo "3. the sample corpus is in the tree"
	@test -f samples/manifest.json && echo "   samples/manifest.json present"
	@echo "4. migrations have one head"
	@cd $(SERVER) && uv run alembic heads | tee /dev/stderr | grep -c "(head)" | grep -qx 1
	@echo "5. no secret is committed"
	@! git ls-files | grep -qE '(^|/)\.env$$' && echo "   no .env tracked by git"
	@echo
	@echo "Good. docs/deployment.md is the rest."

.PHONY: clean
clean: ## Remove build output and caches, leaving dependencies alone
	rm -rf $(CLIENT)/dist
	rm -rf $(SERVER)/var/storage $(SERVER)/var/test-storage
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
