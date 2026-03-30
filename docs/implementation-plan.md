# pggraphrag-mcp 実装計画

## 1. 目的

`pggraphrag-mcp` は、文書、チャンク、エンティティ、関係、検索トレースを PostgreSQL に永続化しつつ、
`pgvector` による近傍検索と `Apache AGE` によるグラフ展開を組み合わせて、
MCP クライアントから安全に GraphRAG を利用できるようにする。

## 2. スコープ

### In scope

- HTTPS で到達可能な Remote MCP サーバ
- Docker Compose ベースの単一ノード構成
- Traefik による TLS 終端
- Bearer token ベースの small auth
- PostgreSQL 17 + pgvector + Apache AGE
- GraphRAG 用 tool / resource の公開
- 文書投入、再投入、削除
- naive / local_graph / hybrid retrieval
- graph refresh / index rebuild
- 構造化ログ
- smoke test

### Out of scope（初期版ではやらない）

- Grafana
- OIDC / OAuth2 本実装
- マルチノード運用
- ジョブキュー基盤の外出し
- 高度な community detection の自動学習
- 任意 SQL/Cypher 実行 UI

## 3. 非機能要件

- すべての外部アクセスは HTTPS のみ
- private app コンテナは外部公開しない
- auth gateway を通らない限り `/mcp` は利用不可
- DB 接続は least privilege
- 再実行可能な bootstrap 手順
- すべての retrieval 結果に source trace を付与
- request / tool execution / DB access は相関 ID で追跡可能

## 4. コンテナ構成

### 4.1 サービス一覧

1. `pggraphrag-mcp-proxy`
   - Traefik
   - 443/8443 受け口
   - TLS termination
   - `/mcp` を auth 付きで backend へルーティング

2. `pggraphrag-mcp-auth`
   - small auth service
   - Bearer token 検証
   - 将来の OIDC 化に備えた独立境界

3. `pggraphrag-mcp-private`
   - FastAPI + uvicorn
   - MCP HTTP endpoint 提供
   - ingestion / retrieval / graph refresh を実装

4. `pggraphrag-db`
   - PostgreSQL 17
   - `pgvector` / `Apache AGE` を repository-owned image で提供

### 4.2 ネットワーク

- `edge_net`
  - proxy と auth のみ外部境界側に参加
- `app_net`
  - proxy, auth, private app, db の内部通信
- DB は host port を公開しない
- private app は host port を公開しない

## 5. データモデル方針

### 5.1 canonical relational tables

- `document`
  - `document_id`
  - `tenant_id`
  - `source_uri`
  - `title`
  - `mime_type`
  - `content_hash`
  - `status`
  - `created_at`
  - `updated_at`

- `chunk`
  - `chunk_id`
  - `document_id`
  - `chunk_no`
  - `text`
  - `token_count`
  - `embedding vector(...)`
  - `metadata jsonb`

- `entity`
  - `entity_id`
  - `canonical_name`
  - `entity_type`
  - `aliases jsonb`
  - `metadata jsonb`

- `chunk_entity`
  - chunk と entity の mention 関係

- `relation_fact`
  - `relation_fact_id`
  - `source_entity_id`
  - `target_entity_id`
  - `relation_type`
  - `weight`
  - `evidence_chunk_id`

- `ingestion_job`
  - 状態管理、再試行、失敗理由

- `retrieval_log`
  - query, mode, timings, returned source ids

### 5.2 derived graph in Apache AGE

- `(:Document {document_id})`
- `(:Chunk {chunk_id})`
- `(:Entity {entity_id, canonical_name, entity_type})`
- relations:
  - `(:Document)-[:HAS_CHUNK]->(:Chunk)`
  - `(:Chunk)-[:MENTIONS]->(:Entity)`
  - `(:Entity)-[:RELATES_TO {relation_type, weight}]->(:Entity)`

### 5.3 原則

- 正は relational tables に置く
- AGE は再生成可能な derived graph とみなす
- retrieval に必要な ID は relational 側と相互参照可能にする

## 6. MCP インターフェース設計

### 6.1 tools

#### ingestion 系
- `document_ingest`
- `document_reingest`
- `document_delete`
- `graph_refresh`
- `rebuild_embeddings`

#### retrieval 系
- `retrieve_naive`
- `retrieve_local_graph`
- `retrieve_hybrid`
- `entity_search`
- `entity_expand`
- `source_trace`

#### ops 系
- `health_check`
- `index_status`
- `graph_status`

### 6.2 resources

- `graphrag://document/{document_id}`
- `graphrag://chunk/{chunk_id}`
- `graphrag://entity/{entity_id}`
- `graphrag://retrieval/{retrieval_id}`
- `graphrag://graph/status`

### 6.3 返却フォーマット方針

各 retrieval は最低限以下を返す。

- `summary`
- `mode`
- `supporting_chunks`
- `entities`
- `relationships`
- `sources`
- `confidence`
- `retrieval_id`

## 7. Retrieval フロー

### 7.1 naive

1. クエリを正規化
2. embedding 作成
3. `pgvector` で top-k chunk 抽出
4. chunk を再スコアリング
5. source trace 付きで返却

### 7.2 local_graph

1. naive の候補取得
2. chunk に紐づく entities を抽出
3. AGE で 1 hop 展開
4. relation type / weight でフィルタ
5. chunk + graph context を返却

### 7.3 hybrid

1. naive 候補取得
2. entities 抽出
3. AGE で 1〜2 hop 展開
4. relation evidence を relational から回収
5. chunk relevance + graph evidence + recency を合成スコア化
6. summary と supporting evidence を返却

## 8. セキュリティ方針

- app は proxy 背後のみで待ち受ける
- small auth で Bearer token を検証
- app へは認証済み identity header のみ渡す
- 任意 SQL / 任意 Cypher tool は公開しない
- DB role は app 用と migration 用で分離
- retrieval は read-only の repository 層を使う
- ingestion / refresh は明示的 tool または管理コマンドのみ
- top-k / graph hops / payload size を制限する

## 9. 設定方針

### 9.1 主要環境変数

- `PGGRAPHRAG_MCP_APP_NAME`
- `PGGRAPHRAG_MCP_APP_VERSION`
- `PGGRAPHRAG_MCP_ENV`
- `PGGRAPHRAG_MCP_HTTP_PATH`
- `PGGRAPHRAG_MCP_DATABASE_URL`
- `PGGRAPHRAG_MCP_SMALL_AUTH_TOKEN`
- `PGGRAPHRAG_MCP_AGE_GRAPH_NAME`
- `PGGRAPHRAG_MCP_EMBEDDING_PROVIDER`
- `PGGRAPHRAG_MCP_EMBEDDING_MODEL`
- `PGGRAPHRAG_MCP_EMBEDDING_DIMENSIONS`
- `PGGRAPHRAG_MCP_MAX_VECTOR_CANDIDATES`
- `PGGRAPHRAG_MCP_MAX_GRAPH_HOPS`
- `PGGRAPHRAG_MCP_MAX_RETURN_CHUNKS`
- `PGGRAPHRAG_MCP_MAX_RETURN_ENTITIES`
- `PGGRAPHRAG_MCP_ENABLE_DEBUG_ENDPOINTS`

### 9.2 secrets 方針

- ローカルは `.env`
- 本番は secrets manager または inject
- bearer token はローテーション可能に設計
- OpenAI 等の API key は app コンテナにのみ注入

## 10. リポジトリ構成案

```text
pggraphrag-mcp/
  docker/
    docker-compose.yml
    docker-compose.small-auth.yml
    traefik/
      dynamic.yml
      certs/
    postgres-age/
      Dockerfile
  scripts/
    apply_schema.py
    ensure_age_extension.py
    bootstrap_graph.py
    refresh_graph.py
    mcp_http_smoke.py
    populate_env_placeholders.py
  schemas/
    mcp-tools/
    resources/
  src/
    pggraphrag_mcp/
      http_app.py
      config.py
      logging.py
      auth_context.py
      mcp/
        tools.py
        resources.py
        schemas.py
      application/
        ingestion_service.py
        retrieval_service.py
        graph_service.py
      domain/
        models.py
        policies.py
      infrastructure/
        db/
        repositories/
        embeddings/
        age/
  tests/
    integration/
    unit/
  docs/
    project/
      product/
```

## 11. 実装フェーズ

### Phase 0: bootstrap

- リポジトリ雛形作成
- Docker Compose の雛形作成
- env 変数命名確定
- Traefik / auth / private app / db の起動確認

### Phase 1: storage baseline

- PostgreSQL image 作成
- `pgvector` / `Apache AGE` 組み込み
- schema migration 実装
- `ensure_age_extension` / `bootstrap_graph` 実装

### Phase 2: MCP skeleton

- MCP HTTP endpoint 実装
- `health_check`, `index_status`, `graph_status` 実装
- tool schema / resource schema 定義
- smoke test 作成

### Phase 3: ingestion

- document ingest
- chunking
- embedding
- entity extraction
- relation extraction
- relational persistence
- graph refresh

### Phase 4: retrieval

- `retrieve_naive`
- `entity_search`
- `entity_expand`
- `retrieve_local_graph`
- `retrieve_hybrid`
- `source_trace`

### Phase 5: hardening

- rate limiting
- payload limit
- structured logging
- timeout / retry policy
- acceptance tests
- production compose review

## 12. テスト計画

### unit tests
- query normalization
- score aggregation
- entity deduplication
- source trace formatting

### integration tests
- auth なしで 401
- auth ありで `/mcp` が応答
- ingest 後に naive retrieval が成功
- graph refresh 後に entity_expand が成功
- hybrid retrieval が source trace を返す

### operational smoke
- compose up
- DB ready
- schema applied
- AGE ready
- `/mcp` health check
- authenticated retrieval scenario

## 13. 初期リリース定義

### v0.1.0 に含めるもの
- HTTPS remote MCP
- small auth
- PostgreSQL 17 + pgvector + Apache AGE
- document ingest
- retrieve_naive
- retrieve_local_graph
- retrieve_hybrid
- entity_search / entity_expand
- source_trace
- smoke tests

### v0.1.0 に含めないもの
- Grafana
- OIDC
- tenant-aware RLS
- async worker externalization
- advanced graph summarization

## 14. 完了条件

- docs の quick start だけで起動可能
- auth なしで拒否される
- auth ありで retrieval が成功する
- ingest した文書から source trace が取得できる
- graph rebuild が再実行可能
- テストと smoke が CI で通る

