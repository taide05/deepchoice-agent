# Pydantic v2 vs dataclasses

**Category**: Backend Frameworks & API
**Expected winner**: Pydantic v2

## Analysis

Pydantic v2 adds runtime validation, coercion, nested model support, JSON Schema generation, and serialization. Dataclasses are purely a syntax convenience over writing __init__ manually. For production API validation, Pydantic v2 is the clear winner. Rust core (pydantic-core) makes v2 5-50x faster than v1.

## Known Contradictions

### Performance overhead
- Position A: Pydantic validation adds runtime overhead that dataclasses avoid
- Position B: Pydantic v2's Rust core is faster than hand-written validation; the overhead argument is outdated
