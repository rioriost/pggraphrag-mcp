# pggraphrag-mcp

`pggraphrag-mcp` は、PostgreSQL 上で動作する GraphRAG 向けの remote MCP server です。

以下を提供します。

- HTTPS で到達できる MCP endpoint
- small bearer-token 認証
- PostgreSQL 17 + `pgvector` + `Apache AGE`
- document ingest と GraphRAG retrieval
- retrieval response に対する source trace
- ローカル開発・評価向けの Docker Compose 起動フロー

---

## 利用者向け

### 何が得られるか

デフォルトのローカル構成では、以下が利用できます。

- MCP endpoint
  - `https://localhost:9443/mcp`
- authenticated HTTPS access
- Traefik 配下の private MCP app
- PostgreSQL を canonical storage とした GraphRAG 基盤
- Apache AGE を使った派生グラフ文脈
- ローカル起動時に生成される bearer token
- 初回起動時に自動生成される `.env` と TLS ファイル

### 現在の完成状況

`pggraphrag-mcp` は、GraphRAG 向け remote MCP server として動作しています。

確認済みの内容:

- AI エージェントからの HTTPS MCP registration
- live MCP tool discovery
- `document_ingest`
- `retrieve_naive`
- `retrieve_local_graph`
- `retrieve_hybrid`
- `entity_search`
- `source_trace`

つまり、以下の core flow は end-to-end で動いています。

- 文書を PostgreSQL の canonical storage に ingest
- Apache AGE による派生グラフ文脈を利用
- supporting chunks / entities / relationships / sources を MCP 経由で retrieval

### 利用可能な MCP tools

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

## Quick start

### 1. リポジトリを取得

```text
git clone https://github.com/rioriost/pggraphrag-mcp.git
cd pggraphrag-mcp
```

### 2. ローカルスタックを起動

実行:

```text
make compose-up
```

これが標準の初回 bootstrap 手順です。

`compose-up` は、必要なローカル前提を自動で準備します。

- `.env.example` から `.env` を生成
- `OPENAI_API_KEY` の入力を促す
- ローカル用 bearer token を生成
- ローカル用 DB password を生成
- 対応する PostgreSQL URL を生成
- まず `9443` を優先しつつ、空いている HTTPS port を選ぶ
- `docker/traefik/certs` 配下に self-signed TLS ファイルを生成

初回は次の入力を求められます。

```text
Input OpenAI API Key:
```

対話を避けたい場合は、先に値を渡せます。

```text
OPENAI_API_KEY=your-key-here make compose-up
```

### 3. 起動完了を待つ

`make compose-up` が成功すると、最後に AI エージェントへ登録するための MCP 設定 JSON が表示されます。

例:

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

表示された実際の値を使ってください。

### 4. AI エージェントに MCP server を登録

`make compose-up` が表示した JSON をそのまま利用します。

重要な値は次の2つです。

- URL
  - `https://localhost:<your-port>/mcp`
- Header
  - `Authorization: Bearer <your-generated-token>`

### 5. サーバーを検証

smoke test を実行します。

```text
uv run python scripts/mcp_http_smoke.py --base-url https://localhost:9443 --mcp-path /mcp --bearer-token <your-generated-token> --insecure
```

もし bootstrap 時に `9443` 以外の port が選ばれた場合は、その値に置き換えてください。

この smoke test では以下を確認します。

- unauthorized request rejection
- authenticated `health_check`
- authenticated `index_status`
- seeded `document_ingest`
- authenticated `retrieve_hybrid`
- authenticated `source_trace`

### 6. MCP tool 利用例

AI エージェント接続後、最初の確認として `health_check` を呼ぶのが簡単です。

JSON-RPC request body 例:

```text
{"jsonrpc":"2.0","id":"example-1","method":"tools/call","params":{"name":"health_check","arguments":{}}}
```

`curl` 例:

```text
curl -k https://localhost:9443/mcp -H "Authorization: Bearer <your-generated-token>" -H "Content-Type: application/json" -d '{"jsonrpc":"2.0","id":"example-1","method":"tools/call","params":{"name":"health_check","arguments":{}}}'
```

同じ形式で、以下の tools も呼べます。

- `index_status`
- `graph_status`
- `document_ingest`
- `retrieve_naive`
- `retrieve_local_graph`
- `retrieve_hybrid`
- `source_trace`

---

## SSL/TLS troubleshooting

AI エージェントや他の client が certificate trust error を出す場合、まず Traefik がどの証明書を返しているか確認します。

### 1. 実際に返されている証明書を確認

```text
openssl s_client -connect localhost:9443 -servername localhost < /dev/null 2>/dev/null | openssl x509 -noout -subject -issuer
```

期待される出力:

```text
subject=CN=localhost
issuer=CN=localhost
```

もし `TRAEFIK DEFAULT CERT` が出る場合は、ローカル証明書が正しく選ばれていません。

### 2. macOS でローカル証明書を trust する

生成される証明書ファイルは次です。

```text
docker/traefik/certs/dev.crt
```

macOS では、この証明書を Keychain Access に追加し、trust 設定を変更します。

一般的な流れ:

- `docker/traefik/certs/dev.crt` を開く
- Keychain Access に追加
- 証明書の詳細を開く
- Trust セクションで “Always Trust” を選ぶ

### 3. AI エージェント接続を再試行

その後、次の endpoint へ再接続します。

```text
https://localhost:9443/mcp
```

もし bootstrap helper が別の port を選んでいた場合は、`.env` に書かれた `PGGRAPHRAG_MCP_PROXY_PORT` を使ってください。

---

## オプション

### 対話なしで API key を渡す

```text
OPENAI_API_KEY=your-key-here make compose-up
```

### ログを見る

```text
make compose-logs
```

### スタックを止める

```text
make compose-down
```

### smoke test を再実行する

```text
uv run python scripts/mcp_http_smoke.py --base-url https://localhost:9443 --mcp-path /mcp --bearer-token <your-generated-token> --insecure
```

### `.env` を手動で作る

完全に手動で管理したい場合:

```text
cp .env.example .env
```

その後、少なくとも次を設定してください。

- `OPENAI_API_KEY`
- `PGGRAPHRAG_MCP_SMALL_AUTH_TOKEN`
- `AUTH_SMALL_BEARER_TOKEN`
- `PGGRAPHRAG_MCP_DB_PASSWORD`
- `PGGRAPHRAG_MCP_DATABASE_URL`

### TLS ファイルを手動で作る

必要なら自分で証明書を生成できます。

```text
mkdir -p docker/traefik/certs
openssl req -x509 -nodes -days 365 -newkey rsa:2048 -keyout docker/traefik/certs/dev.key -out docker/traefik/certs/dev.crt -subj "/CN=localhost"
```

---

## 開発者向け

`pggraphrag-mcp` は次の構成を前提にしています。

- Traefik を HTTPS reverse proxy として利用
- small bearer-token auth gateway
- private FastAPI MCP app
- PostgreSQL 17 + `pgvector` + `Apache AGE`

現在の開発方針:

- PostgreSQL が canonical system of record
- `pgvector` と `Apache AGE` は derived support layer
- arbitrary SQL / arbitrary Cypher は公開しない
- public MCP surface は bounded
- local bootstrap は quick startup を優先

### リポジトリ構成

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

### 開発コマンド

#### Lint

```text
make lint
```

または:

```text
uv run ruff check .
```

#### Test

```text
make test
```

または:

```text
uv run pytest
```

#### Build

```text
uv build
```

#### Compose 外で app を起動

```text
uv run pggraphrag-mcp serve --reload
```

### 主なスクリプト

- `scripts/apply_schema.py`
- `scripts/bootstrap_graph.py`
- `scripts/bootstrap_local_env.py`
- `scripts/mcp_http_smoke.py`
- `scripts/ops_automation.py`

### 参照ドキュメント

- `docs/operations/ci-and-smoke.md`
- `docs/operations/graph-bootstrap.md`
- `docs/release-checklist.md`
- `docs/ticket-status.md`

### public tool surface

現在の `v0.1.0` public tool surface は以下です。

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