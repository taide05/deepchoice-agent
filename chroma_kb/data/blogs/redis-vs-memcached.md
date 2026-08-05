# Redis vs Memcached

**Category**: Infrastructure
**Expected winner**: Redis

## Analysis

Redis has richer data structures (lists, hashes, sets, sorted sets), persistence options, and built-in replication. Memcached is purely a key-value cache. For modern backend caching, Redis wins unless you have extreme memory efficiency requirements and only need simple get/set.

## Known Contradictions

### Memory efficiency
- Position A: Memcached is more memory-efficient for simple key-value workloads
- Position B: Redis' memory overhead is negligible in practice and worth it for the data structure flexibility
