# Redis vs PostgreSQL

**Category**: Infrastructure
**Expected winner**: Redis

## Analysis

Redis's in-memory storage, TTL-based expiry, and sub-millisecond latency make it the ideal session store. PostgreSQL can store sessions but disk I/O per request adds unnecessary latency for ephemeral session data.

## Known Contradictions

### Infrastructure simplicity
- Position A: Using PostgreSQL for sessions means one less service to manage
- Position B: The latency penalty of disk-based session lookups on every request outweighs the operational simplicity of having one less service
