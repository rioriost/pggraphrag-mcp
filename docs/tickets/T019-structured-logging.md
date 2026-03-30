# T019 Structured logging

## Goal
Make operation debugging possible without Grafana.

## Tasks
- Add JSON logs
- Include correlation IDs, tool name, auth subject, timings, DB spans
- Distinguish app logs and proxy/auth logs
- Document log fields

## Done when
- A single retrieval request can be followed across proxy, auth, app, and DB operation logs
