# T009 Smoke test

## Goal
Verify endpoint behavior end-to-end.

## Tasks
- Implement `scripts/mcp_http_smoke.py`
- Add scenario for unauthorized access expecting 401
- Add scenario for authenticated health check
- Add scenario for authenticated minimal tool invocation

## Done when
- Smoke script fails on auth regressions and passes on healthy compose stack
