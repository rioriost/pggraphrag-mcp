# T011 Embedding pipeline

## Goal
Add vectorization for chunk retrieval.

## Tasks
- Add embedding provider abstraction
- Implement OpenAI provider first
- Persist embeddings to `chunk.embedding`
- Add failure handling and retry semantics

## Done when
- Newly ingested chunks have embeddings and can be searched by vector similarity
