# T007 HTTP app skeleton

## Goal
Create the FastAPI/uvicorn host for remote MCP.

## Tasks
- Add `http_app.py`
- Add config loading and structured logging setup
- Expose `/mcp` route and minimal readiness route
- Wire auth context headers from proxy

## Done when
- Authenticated request reaches the app and unauthenticated direct host access is impossible by topology
