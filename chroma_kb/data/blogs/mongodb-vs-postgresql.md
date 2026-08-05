# MongoDB vs PostgreSQL

**Category**: Infrastructure
**Expected winner**: PostgreSQL

## Analysis

PostgreSQL's JSONB column type gives you document-store flexibility within a relational database. For CMS, you often need both flexible content fields AND relational data (users, permissions, taxonomies). PG gives you both. MongoDB is better for pure document workloads with no relational queries needed.

## Known Contradictions

### Schema flexibility vs data integrity
- Position A: MongoDB's schemaless design is truly flexible - no migrations needed
- Position B: Schemaless means schema-in-code; you'll regret not having constraints when the data grows and multiple services write to the same collection
