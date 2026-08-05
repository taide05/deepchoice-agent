# Uvicorn vs Gunicorn

**Category**: Backend Frameworks & API
**Expected winner**: Uvicorn

## Analysis

FastAPI is async-native and Uvicorn is the recommended ASGI server. Gunicorn is a WSGI server that needs uvicorn workers to serve async apps. Using Uvicorn directly (or with Gunicorn as a process manager) is the standard deployment. The real answer: Gunicorn + Uvicorn workers for multi-process, standalone Uvicorn for single-process.

## Known Contradictions

### Process management
- Position A: Gunicorn is needed for multi-process management and graceful restarts
- Position B: Uvicorn has built-in --workers flag; for containerized deployments where the orchestrator handles process management, standalone Uvicorn is simpler
