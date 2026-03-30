# T002 Compose topology

## Goal
Reproduce a ctxledger-like container topology without Grafana.

## Tasks
- Add `docker/docker-compose.yml` with `pggraphrag-db` and `pggraphrag-mcp-private`
- Add `docker/docker-compose.small-auth.yml` with `pggraphrag-mcp-proxy` and `pggraphrag-mcp-auth`
- Define internal and edge networks
- Ensure only proxy publishes host ports
- Add healthchecks and dependency ordering

## Done when
- `docker compose config` validates successfully
- Private app and DB are not exposed on the host
