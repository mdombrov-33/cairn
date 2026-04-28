.DEFAULT_GOAL := help

# Infrastructure

# Start composer in the background (detached).
up:
	docker compose up -d

# Start composer in the foreground (attached).
up-fg:
	docker compose up

# Stop and remove containers (volume preserved).
down:
	docker compose down

# Stop and remove containers AND wipe the postgres volume.
nuke:
	docker compose down -v

# Tail postgres logs.
logs:
	docker compose logs -f

# Drop into a psql shell on the running postgres container.
psql:
	docker exec -it cairn-postgres-1 psql -U cairn -d cairn

# Dev

# Install / sync dependencies. Run after pulling new code or editing pyproject.
install:
	cd backend && uv sync

# Run the API with hot reload.
dev:
	cd backend && uv run uvicorn cairn.main:app --reload

# Drop into a Python repl with the venv active.
shell:
	cd backend && uv run python

# Quality

# Run all tests.
test:
	cd backend && uv run pytest

# Format code with ruff.
fmt:
	cd backend && uv run ruff format .

# Report lint findings (no mutation).
lint:
	cd backend && uv run ruff check .

# Apply all auto-fixable formatting and lint fixes.
fix:
	cd backend && uv run ruff format . && uv run ruff check --fix .

# Run the type checker.
typecheck:
	cd backend && uv run mypy .

# Full quality gate — what CI runs. No mutation.
check:
	cd backend && uv run ruff format --check . && uv run ruff check . && uv run mypy . && uv run pytest

# Migrations

# Apply all pending migrations against the running postgres.
migrate:
	cd backend && uv run alembic upgrade head

# Roll back the last applied migration.
downgrade:
	cd backend && uv run alembic downgrade -1

# Show current migration revision in the DB.
current:
	cd backend && uv run alembic current

# Autogenerate a migration. Usage:  make revision m="add sessions table"
revision:
	cd backend && uv run alembic revision --autogenerate -m "$(m)"

#  Help

# List all targets with their leading comment.
help:
	@awk 'BEGIN{FS=":"} /^# /{c=substr($$0,3)} /^[a-zA-Z][a-zA-Z0-9_-]*:/ && c{printf "  %-12s  %s\n", $$1, c; c=""}' $(MAKEFILE_LIST)

.PHONY: up up-fg down nuke logs psql install dev shell test fmt lint fix typecheck check migrate downgrade current revision help
