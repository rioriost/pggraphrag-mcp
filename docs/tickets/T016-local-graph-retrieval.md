# T016 Local graph retrieval

## Goal
Augment vector retrieval with immediate graph context.

## Tasks
- Take naive chunk candidates
- Resolve entities mentioned by those chunks
- Expand 1-hop graph neighborhood
- Merge chunk and graph evidence into one response

## Done when
- `retrieve_local_graph` returns both textual and relational support
