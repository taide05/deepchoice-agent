# ChromaDB vs FAISS

**Category**: Models & Data
**Expected winner**: ChromaDB

## Analysis

ChromaDB has a simpler Python API, built-in metadata filtering, and persistent storage out of the box. FAISS is faster for pure vector search but requires manual metadata handling and is in-memory only without extra work. For laptop-scale RAG, ChromaDB wins on developer experience.

## Known Contradictions

### Search speed
- Position A: FAISS is 10-100x faster for exact and approximate nearest neighbor search
- Position B: At laptop scale (<1M vectors), the speed difference is imperceptible; metadata filtering and persistence matter more
