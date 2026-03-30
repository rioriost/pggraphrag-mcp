# docker / deployment layout

## Compose 方針

- `docker/docker-compose.yml`
  - db
  - private app
- `docker/docker-compose.small-auth.yml`
  - traefik
  - auth gateway

## services

### pggraphrag-db
- internal only
- named volume で data 永続化
- healthcheck 必須

### pggraphrag-mcp-private
- internal only
- `/mcp` は proxy 経由のみ
- migration 用 CLI を同イメージに同梱

### pggraphrag-mcp-auth
- edge + app network の両方に所属
- Authorization ヘッダ検査
- app に subject / scopes を転送

### pggraphrag-mcp-proxy
- 443/8443 exposed
- TLS cert mount
- `/mcp` を auth gateway 経由で app へ転送

## Volumes

- `pggraphrag_db_data`
- `pggraphrag_traefik_certs`

## Secrets

- bearer token
- db password
- external embedding api key

## 初期起動順

1. db 起動
2. schema 適用
3. AGE extension 確保
4. graph bootstrap
5. private app 起動
6. auth 起動
7. proxy 起動
8. smoke test

## 本番運用原則

- DB backup を最優先
- derived graph は rebuild 可能前提
- app の rolling restart で canonical state を失わない
- cert renewal は proxy 側で処理

