# T013 Graph refresh flow

## Goal
Materialize derived graph state in Apache AGE.

## Tasks
- Convert relational document/chunk/entity/relation rows into AGE nodes/edges
- Support refresh by document and full rebuild modes
- Preserve repeatability and auditability

## Done when
- Entity expansion can traverse graph edges generated from canonical relational facts
