# Ray vs Dask

**Category**: Models & Data
**Expected winner**: Ray

## Analysis

Ray has native actor model, better GPU support, built-in serving (Ray Serve) and training (Ray Train). Dask is better for pure DataFrame/distributed NumPy workloads. For ML pipelines that mix training + serving + hyperparameter tuning, Ray's unified framework wins.

## Known Contradictions

### Simplicity
- Position A: Dask's DataFrame API mirrors Pandas, making it easier to adopt
- Position B: Ray's unified compute model means you learn one framework for training, serving, and tuning — Dask only solves the data-parallel piece
