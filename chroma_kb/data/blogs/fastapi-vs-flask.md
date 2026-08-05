# FastAPI vs Flask

**Category**: Backend Frameworks & API
**Expected winner**: FastAPI

## Analysis

FastAPI has built-in async, auto-generated OpenAPI docs, Pydantic validation. Flask needs extensions for all of these. For team REST API, FastAPI is the modern default.

## Known Contradictions

### Async performance
- Position A: FastAPI async is a must-have for modern APIs
- Position B: Most apps don't need async; Flask + gunicorn is sufficient for 90% of use cases
