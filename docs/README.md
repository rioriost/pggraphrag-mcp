# pggraphrag-mcp 実装計画一式

`pggraphrag-mcp` は、PostgreSQL を canonical state とし、`pgvector` と `Apache AGE` を派生インデックスとして利用する、HTTPS 対応のリモート MCP サーバです。

本パッケージは、`ctxledger` と同様のコンテナ構成を前提にした初期実装計画です。

## 含まれるファイル

- `implementation-plan.md` : 実装計画の本文
- `plan.yaml` : フェーズ・成果物・依存関係を表した実行計画
- `tickets/` : 実装チケット群
- `docker-layout.md` : コンテナ/ネットワーク/秘密情報の配置方針
- `naming-and-env.md` : 命名規則と環境変数方針
- `acceptance-criteria.md` : 受け入れ基準

## 想定アーキテクチャ

- reverse proxy: Traefik
- auth gateway: small auth service
- MCP app: FastAPI + uvicorn
- DB: PostgreSQL 17 + pgvector + Apache AGE
- protocol: Remote MCP over HTTPS (`/mcp`)

## 実装原則

1. PostgreSQL を truth とする
2. Apache AGE / pgvector は再構築可能な派生層として扱う
3. 任意 SQL / 任意 Cypher は公開しない
4. MCP では有限個の tool / resource のみ公開する
5. 認証は proxy 層で始め、将来 OIDC へ差し替え可能にする
6. スキーマ適用と graph bootstrap は明示的運用手順にする

