# T004 PostgreSQL image with pgvector and Apache AGE

## Goal
Build the repository-owned PostgreSQL image.

## Tasks
- Add `docker/postgres-age/Dockerfile`
- Install PostgreSQL 17 compatible build chain
- Build or install `pgvector`
- Build or install `Apache AGE`
- Verify extension availability at container start

## Done when
- `CREATE EXTENSION vector;` and AGE bootstrap preconditions succeed in a test container
