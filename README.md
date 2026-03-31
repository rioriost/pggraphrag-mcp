# pggraphrag-mcp

`pggraphrag-mcp` is a remote MCP server for GraphRAG on PostgreSQL.

It provides:
- an HTTPS MCP endpoint
- small bearer-token authentication
- PostgreSQL 17 with `pgvector` and `Apache AGE`
- document ingest and GraphRAG retrieval flows
- source trace for retrieval responses
- local Docker Compose startup for development and evaluation

---

## For users

### What you get

The default local setup gives you:

- MCP endpoint:
  - `https://localhost:9443/mcp`
- authenticated HTTPS access
- a private FastAPI-based MCP app behind Traefik
- PostgreSQL-backed canonical storage
- graph-backed retrieval support through Apache AGE
- a generated local bearer token for MCP access
- a generated local `.env` file and local TLS files on first run

Available MCP tools include:

- `health_check`
- `index_status`
- `graph_status`
- `document_ingest`
- `document_reingest`
- `document_delete`
- `graph_refresh`
- `retrieve_naive`
- `entity_search`
- `entity_expand`
- `retrieve_local_graph`
- `retrieve_hybrid`
- `source_trace`

### Quick start

#### 1. Clone the repository

```text
git clone https://github.com/rioriost/pggraphrag-mcp.git
cd pggraphrag-mcp
```

#### 2. Start the local stack

Run:

```text
make compose-up
```

On first run, the bootstrap flow will automatically:

- create `.env` from `.env.example`
- generate a random local MCP bearer token
- generate a random local database password
- generate a matching local PostgreSQL URL
- choose a free local HTTPS port, preferring `9443`
- generate self-signed local TLS files under `docker/traefik/certs`
- prompt for your OpenAI API key

Expected prompt:

```text
Input OpenAI API Key:
```

If you prefer not to type the key interactively, you can provide it up front:

```text
OPENAI_API_KEY=your-key-here make compose-up
```

#### 3. Wait for successful startup

A successful `make compose-up` ends by printing a ready-to-copy MCP configuration example for your AI agent.

It will look like this:

```json
{
  "pggraphrag-mcp": {
    "url": "https://localhost:9443/mcp",
    "headers": {
      "Authorization": "Bearer <generated-token>"
    }
  }
}
```

Use the actual values printed by your local run.

#### 4. Register the MCP server in your AI agent

Use the generated JSON example printed by `make compose-up`.

If your agent expects a named remote MCP server entry, the important fields are:

- URL:
  - `https://localhost:<your-port>/mcp`
- Header:
  - `Authorization: Bearer <your-generated-token>`

#### 5. Verify the server

Run the smoke test:

```text
uv run python scripts/mcp_http_smoke.py --base-url https://localhost:9443 --mcp-path /mcp --bearer-token <your-generated-token> --insecure
```

If your local bootstrap selected a different port, replace `9443` with the value written into `.env`.

If everything is healthy, the smoke script will verify:

- unauthorized request rejection
- authenticated `health_check`
- authenticated `index_status`
- seeded `document_ingest`
- authenticated `retrieve_hybrid`
- authenticated `source_trace`

#### 6. Example MCP tool usage

Once your AI agent is connected, a simple first action is calling `health_check`.

Example JSON-RPC request body:

```text
{"jsonrpc":"2.0","id":"example-1","method":"tools/call","params":{"name":"health_check","arguments":{}}}
```

Example `curl` request:

```text
curl -k https://localhost:9443/mcp -H "Authorization: Bearer <your-generated-token>" -H "Content-Type: application/json" -d '{"jsonrpc":"2.0","id":"example-1","method":"tools/call","params":{"name":"health_check","arguments":{}}}'
```

You can use the same pattern for other tools such as:

- `index_status`
- `graph_status`
- `document_ingest`
- `retrieve_naive`
- `retrieve_local_graph`
- `retrieve_hybrid`
- `source_trace`

### SSL/TLS troubleshooting

If your AI agent or other client reports a certificate trust error, first verify which certificate Traefik is serving.

#### 1. Check the served certificate

```text
openssl s_client -connect localhost:9443 -servername localhost < /dev/null 2>/dev/null | openssl x509 -noout -subject -issuer
```

Expected output:

```text
subject=CN=localhost
issuer=CN=localhost
```

If you see `TRAEFIK DEFAULT CERT`, the local certificate is not being selected correctly.

#### 2. Trust the local certificate on macOS

The generated certificate file is:

```text
docker/traefik/certs/dev.crt
```

On macOS, open this certificate in Keychain Access and mark it as trusted.

Typical flow:

- open `docker/traefik/certs/dev.crt`
- add it to Keychain Access
- open the certificate details
- under Trust, set the certificate to “Always Trust”

#### 3. Retry the AI agent connection

After trusting the certificate, reconnect your AI agent to:

```text
https://localhost:9443/mcp
```

If your bootstrap selected another port, use that value from `.env`.

### Options

#### Start without interactive API key prompt

```text
OPENAI_API_KEY=your-key-here make compose-up
```

#### Inspect logs

```text
make compose-logs
```

#### Stop the stack

```text
make compose-down
```

#### Run the smoke test again

```text
uv run python scripts/mcp_http_smoke.py --base-url https://localhost:9443 --mcp-path /mcp --bearer-token <your-generated-token> --insecure
```

#### Manual env preparation instead of auto-bootstrap

If you want full manual control:

```text
cp .env.example .env
```

Then set:
- `OPENAI_API_KEY`
- `PGGRAPHRAG_MCP_SMALL_AUTH_TOKEN`
- `AUTH_SMALL_BEARER_TOKEN`
- `PGGRAPHRAG_MCP_DB_PASSWORD`
- `PGGRAPHRAG_MCP_DATABASE_URL`

#### Manual TLS preparation instead of auto-bootstrap

You can generate your own local certificate pair:

```text
mkdir -p docker/traefik/certs
openssl req -x509 -nodes -days 365 -newkey rsa:2048 -keyout docker/traefik/certs/dev.key -out docker/traefik/certs/dev.crt -subj "/CN=localhost"
```

---

## For developers

`pggraphrag-mcp` is structured around:

- Traefik as the HTTPS reverse proxy
- a small bearer-token auth gateway
- a private FastAPI-based MCP app
- PostgreSQL 17 with `pgvector` and `Apache AGE`

Current development posture:

- PostgreSQL is the canonical system of record
- `pgvector` and `Apache AGE` are derived support layers
- arbitrary SQL and arbitrary Cypher are not exposed
- the public MCP surface is intentionally bounded
- local bootstrap is optimized for quick startup

### Repository layout

- `docker/`
- `docs/`
- `schemas/`
- `scripts/`
- `src/pggraphrag_mcp/`
- `tests/`
- `.env.example`
- `.env.production.example`
- `Makefile`
- `pyproject.toml`

### Local development commands

#### Lint

```text
make lint
```

or

```text
uv run ruff check .
```

#### Test

```text
make test
```

or

```text
uv run pytest
```

#### Build

```text
uv build
```

#### Run the app outside Compose

```text
uv run pggraphrag-mcp serve --reload
```

### Operator-facing scripts

Useful scripts include:

- `scripts/apply_schema.py`
- `scripts/bootstrap_graph.py`
- `scripts/bootstrap_local_env.py`
- `scripts/mcp_http_smoke.py`
- `scripts/ops_automation.py`

### Operations docs

See:

- `docs/operations/ci-and-smoke.md`
- `docs/operations/graph-bootstrap.md`
- `docs/release-checklist.md`
- `docs/ticket-status.md`

### Public surface

The current `v0.1.0` public tool surface includes:

- `health_check`
- `index_status`
- `graph_status`
- `document_ingest`
- `document_reingest`
- `document_delete`
- `graph_refresh`
- `retrieve_naive`
- `entity_search`
- `entity_expand`
- `retrieve_local_graph`
- `retrieve_hybrid`
- `source_trace`

---

## License

MIT