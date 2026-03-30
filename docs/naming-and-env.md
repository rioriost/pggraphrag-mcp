# 命名規則と環境変数方針

## 命名

- product / repo: `pggraphrag-mcp`
- python package: `pggraphrag_mcp`
- main service: `pggraphrag-mcp-private`
- proxy: `pggraphrag-mcp-proxy`
- auth: `pggraphrag-mcp-auth`
- db: `pggraphrag-db`

## Docker network / volume

- network: `pggraphrag_edge_net`, `pggraphrag_app_net`
- volume: `pggraphrag_db_data`, `pggraphrag_traefik_certs`

## 環境変数 prefix

すべて `PGGRAPHRAG_MCP_` で始める。

### app
- `PGGRAPHRAG_MCP_APP_NAME=pggraphrag-mcp`
- `PGGRAPHRAG_MCP_APP_VERSION=0.1.0`
- `PGGRAPHRAG_MCP_ENV=production`
- `PGGRAPHRAG_MCP_HTTP_PATH=/mcp`

### auth
- `PGGRAPHRAG_MCP_SMALL_AUTH_TOKEN=`

### db
- `PGGRAPHRAG_MCP_DATABASE_URL=`
- `PGGRAPHRAG_MCP_AGE_GRAPH_NAME=pggraphrag_memory`

### embeddings
- `PGGRAPHRAG_MCP_EMBEDDING_PROVIDER=openai`
- `PGGRAPHRAG_MCP_EMBEDDING_MODEL=text-embedding-3-small`
- `PGGRAPHRAG_MCP_EMBEDDING_DIMENSIONS=1536`

### limits
- `PGGRAPHRAG_MCP_MAX_VECTOR_CANDIDATES=30`
- `PGGRAPHRAG_MCP_MAX_GRAPH_HOPS=2`
- `PGGRAPHRAG_MCP_MAX_RETURN_CHUNKS=12`
- `PGGRAPHRAG_MCP_MAX_RETURN_ENTITIES=20`

### debug
- `PGGRAPHRAG_MCP_ENABLE_DEBUG_ENDPOINTS=false`

