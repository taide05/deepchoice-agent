# FastAPI vs Django Ninja

**Category**: Backend Frameworks & API
**Expected winner**: FastAPI

## Analysis

FastAPI has larger community, more extensions, better documentation. Django Ninja is appealing if you already use Django ORM and want to add async APIs to an existing Django project, but for greenfield, FastAPI wins.

## Known Contradictions

### Django ecosystem
- Position A: If you need Django Admin and ORM, Django Ninja gives you FastAPI-like DX within Django
- Position B: FastAPI + SQLAlchemy + Alembic is a cleaner stack; tying yourself to Django for the admin is a bad architectural decision
