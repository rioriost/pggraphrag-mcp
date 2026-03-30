# 受け入れ基準

## A. 起動

- [ ] `docker compose` で全サービスが起動する
- [ ] private app と db は直接外部公開されない
- [ ] `/mcp` が HTTPS で到達できる

## B. 認証

- [ ] bearer token なしで `/mcp` は拒否される
- [ ] bearer token ありで `/mcp` は利用できる

## C. 永続化

- [ ] ingest した document が `document` に記録される
- [ ] chunk が `chunk` に保存される
- [ ] entity / relation が relational に保存される
- [ ] graph refresh 後に AGE 上へ反映される

## D. retrieval

- [ ] `retrieve_naive` が supporting_chunks を返す
- [ ] `retrieve_local_graph` が entities と relationships を返す
- [ ] `retrieve_hybrid` が sources と retrieval_id を返す
- [ ] `source_trace` が原文脈へ遡れる

## E. 運用

- [ ] schema 適用が明示的スクリプトで実行できる
- [ ] graph bootstrap が再実行可能
- [ ] smoke test が成功する
- [ ] structured logging が有効

