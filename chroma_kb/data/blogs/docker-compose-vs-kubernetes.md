# Docker Compose vs Kubernetes

**Category**: Deployment & Operations
**Expected winner**: Docker Compose

## Analysis

For 5 services on a single host, Docker Compose is the right tool. K8s adds meaningful complexity (pod networking, ingress controllers, RBAC, etc.) that only pays off when you need multi-host orchestration, auto-scaling, or rolling updates with zero-downtime. Start with Compose, migrate to K8s when you outgrow it.

## Known Contradictions

### Future-proofing
- Position A: Start with K8s even for 5 services - migrating later is painful
- Position B: Docker Compose to K8s migration with Kompose is straightforward for simple setups; premature K8s adoption is the bigger risk
