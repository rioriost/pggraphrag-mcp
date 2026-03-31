ENV_FILE ?= .env
ENV_EXAMPLE ?= .env.example
COMPOSE_PROJECT_NAME ?= pggraphrag_mcp
DEV_CERT_DIR ?= docker/traefik/certs
DEV_CERT_FILE ?= $(DEV_CERT_DIR)/dev.crt
DEV_KEY_FILE ?= $(DEV_CERT_DIR)/dev.key
LOCAL_PROXY_PORT ?= 9443
LOCAL_AUTH_TOKEN ?= change-me-local-token
LOCAL_DB_PASSWORD ?= change-me-db-password
LOCAL_DATABASE_URL ?= postgresql://pggraphrag_app:$(LOCAL_DB_PASSWORD)@pggraphrag-db:5432/pggraphrag
OPENAI_API_KEY ?=
ENV_BOOTSTRAP_SCRIPT ?= scripts/bootstrap_local_env.py

ifneq (,$(wildcard $(ENV_FILE)))
include $(ENV_FILE)
export $(shell sed -n 's/^\([A-Za-z_][A-Za-z0-9_]*\)=.*/\1/p' $(ENV_FILE))
endif

.PHONY: help build test lint smoke compose-up compose-down compose-logs ensure-local-env ensure-dev-cert

help:
	@echo "Available targets:"
	@echo "  build            Build the package"
	@echo "  test             Run the test suite"
	@echo "  lint             Run lint checks"
	@echo "  smoke            Run smoke tests"
	@echo "  ensure-local-env Create or update a local .env file via Python bootstrap helper"
	@echo "  ensure-dev-cert  Create local self-signed TLS assets when missing"
	@echo "  compose-up       Start the compose stack"
	@echo "  compose-down     Stop the compose stack"
	@echo "  compose-logs     Tail compose logs"

build:
	uv build

test:
	uv run pytest

lint:
	uv run ruff check .

smoke:
	PGGRAPHRAG_MCP_SMALL_AUTH_TOKEN="$${PGGRAPHRAG_MCP_SMALL_AUTH_TOKEN:-change-me-local-token}" uv run python scripts/mcp_http_smoke.py --base-url "https://localhost:$${PGGRAPHRAG_MCP_PROXY_PORT:-8443}" --mcp-path /mcp --bearer-token "$${PGGRAPHRAG_MCP_SMALL_AUTH_TOKEN:-change-me-local-token}" --insecure

ensure-local-env:
	@if [ -n "$(OPENAI_API_KEY)" ]; then \
		python "$(ENV_BOOTSTRAP_SCRIPT)" --env-file "$(ENV_FILE)" --env-example "$(ENV_EXAMPLE)" --openai-api-key "$(OPENAI_API_KEY)"; \
	else \
		python "$(ENV_BOOTSTRAP_SCRIPT)" --env-file "$(ENV_FILE)" --env-example "$(ENV_EXAMPLE)"; \
	fi

ensure-dev-cert:
	@mkdir -p "$(DEV_CERT_DIR)"
	@if [ ! -f "$(DEV_CERT_FILE)" ] || [ ! -f "$(DEV_KEY_FILE)" ]; then \
		openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
			-keyout "$(DEV_KEY_FILE)" \
			-out "$(DEV_CERT_FILE)" \
			-subj "/CN=localhost"; \
	fi

compose-up: ensure-local-env ensure-dev-cert
	COMPOSE_PROJECT_NAME="$$(sed -n 's/^COMPOSE_PROJECT_NAME=//p' $(ENV_FILE) | tail -n 1)" docker compose --env-file $(ENV_FILE) -f docker/docker-compose.yml -f docker/docker-compose.small-auth.yml up -d --build
	@proxy_port="$$(sed -n 's/^PGGRAPHRAG_MCP_PROXY_PORT=//p' $(ENV_FILE) | tail -n 1)"; \
	auth_token="$$(sed -n 's/^PGGRAPHRAG_MCP_SMALL_AUTH_TOKEN=//p' $(ENV_FILE) | tail -n 1)"; \
	printf "\n"; \
	echo "compose-up completed successfully."; \
	echo "Next, configure this MCP server in your AI agent."; \
	echo "Example MCP server configuration:"; \
	echo "{"; \
	echo "  \"mcpServers\": {"; \
	echo "    \"pggraphrag-mcp\": {"; \
	echo "      \"transport\": \"streamable-http\","; \
	echo "      \"url\": \"https://localhost:$${proxy_port}/mcp\","; \
	echo "      \"headers\": {"; \
	echo "        \"Authorization\": \"Bearer $${auth_token}\""; \
	echo "      }"; \
	echo "    }"; \
	echo "  }"; \
	echo "}"

compose-down: ensure-local-env
	COMPOSE_PROJECT_NAME="$$(sed -n 's/^COMPOSE_PROJECT_NAME=//p' $(ENV_FILE) | tail -n 1)" docker compose --env-file $(ENV_FILE) -f docker/docker-compose.yml -f docker/docker-compose.small-auth.yml down --remove-orphans

compose-logs: ensure-local-env
	COMPOSE_PROJECT_NAME="$$(sed -n 's/^COMPOSE_PROJECT_NAME=//p' $(ENV_FILE) | tail -n 1)" docker compose --env-file $(ENV_FILE) -f docker/docker-compose.yml -f docker/docker-compose.small-auth.yml logs -f --tail=200
