# Neo4j vs PostgreSQL

**Category**: Infrastructure
**Expected winner**: Neo4j

## Analysis

Neo4j's native graph storage and Cypher query language handle multi-hop traversals (friends-of-friends) in milliseconds. PostgreSQL with recursive CTEs can do graph queries but performance degrades exponentially with depth. For graph-native workloads, Neo4j wins.

## Known Contradictions

### Cost
- Position A: PostgreSQL can handle most graph use cases with recursive CTEs, avoiding another database
- Position B: Recursive CTE performance collapses past 3-4 hops; the database cost is trivial compared to developer time fighting PostgreSQL for graph workloads
