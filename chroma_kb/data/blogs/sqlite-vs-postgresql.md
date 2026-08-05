# SQLite vs PostgreSQL

**Category**: Infrastructure
**Expected winner**: SQLite

## Analysis

SQLite is embedded, zero-config, zero-maintenance, and perfect for single-user desktop apps. PostgreSQL requires a separate server process — massive overkill for a desktop app used by one person at a time.

## Known Contradictions

### Concurrency
- Position A: SQLite has poor concurrent write performance
- Position B: For a single-user desktop app, there IS no concurrent write — the WAL mode handles single-writer perfectly
