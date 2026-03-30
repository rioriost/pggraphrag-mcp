ENV_FILE ?= .env
COMPOSE_PROJECT_NAME ?= pggraphrag_mcp

ifneq (,$(wildcard $(ENV_FILE)))
include $(ENV_FILE)
export $(shell sed -n 's/^\([A-Za-z_][A-Za-z0-9_]*\)=.*/\1/p' $(ENV_FILE))
endif

.PHONY: help build test lint smoke compose-up compose-down compose-logs

help:
	@echo "Available targets:"
	@echo "  build         Build the package"
	@echo "  test          Run the test suite"
	@echo "  lint          Run lint checks"
	@echo "  smoke         Run smoke tests"
	@echo "  compose-up    Start the compose stack"
	@echo "  compose-down  Stop the compose stack"
	@echo "  compose-logs  Tail compose logs"

build:
	uv build

test:
	uv run pytest

lint:
	uv run ruff check .

smoke:
	PGGRAPHRAG_MCP_SMALL_AUTH_TOKEN="$${PGGRAPHRAG_MCP_SMALL_AUTH_TOKEN:-change-me-local-token}" uv run python scripts/mcp_http_smoke.py --base-url "https://localhost:$${PGGRAPHRAG_MCP_PROXY_PORT:-8443}" --mcp-path /mcp --bearer-token "$${PGGRAPHRAG_MCP_SMALL_AUTH_TOKEN:-change-me-local-token}" --insecure

compose-up:
	COMPOSE_PROJECT_NAME=$(COMPOSE_PROJECT_NAME) docker compose --env-file $(ENV_FILE) -f docker/docker-compose.yml -f docker/docker-compose.small-auth.yml up -d --build

compose-down:
	COMPOSE_PROJECT_NAME=$(COMPOSE_PROJECT_NAME) docker compose --env-file $(ENV_FILE) -f docker/docker-compose.yml -f docker/docker-compose.small-auth.yml down --remove-orphans

compose-logs:
	COMPOSE_PROJECT_NAME=$(COMPOSE_PROJECT_NAME) docker compose --env-file $(ENV_FILE) -f docker/docker-compose.yml -f docker/docker-compose.small-auth.yml logs -f --tail=200
