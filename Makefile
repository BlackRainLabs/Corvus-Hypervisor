.PHONY: install test lint fixtures dev-up dev-down dev-status run-turn openapi docker-build docker-up docker-down

VENV_BIN := .venv/bin

install:
	pip install -e ".[dev]"

test:
	CORVUS_USE_TCP=1 $(VENV_BIN)/pytest -q 2>/dev/null || CORVUS_USE_TCP=1 pytest -q

lint:
	$(VENV_BIN)/ruff check src tests 2>/dev/null || ruff check src tests

fixtures:
	$(VENV_BIN)/corvus-policy-fixtures 2>/dev/null || corvus-policy-fixtures

dev-up:
	bash tools/dev-stack.sh up

dev-down:
	bash tools/dev-stack.sh down

dev-status:
	bash tools/dev-stack.sh status

run-turn:
	bash tools/run-turn.sh --once --all-engines

openapi:
	PYTHON=$${PYTHON:-python3} bash tools/export-openapi.sh openapi.json

docker-build:
	docker compose -f deploy/docker-compose.yml build

docker-up:
	docker compose -f deploy/docker-compose.yml up -d

docker-down:
	docker compose -f deploy/docker-compose.yml down
