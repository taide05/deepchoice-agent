# Docker Compose vs Minikube

**Category**: Deployment & Operations
**Expected winner**: Docker Compose

## Analysis

Docker Compose is simpler, lighter, and doesn't require running a full Kubernetes cluster locally. Minikube is valuable when you need to test K8s-specific features (Ingress, RBAC, CRDs) but is overkill for general local development.

## Known Contradictions

### Dev-prod parity
- Position A: Minikube gives you a real K8s environment, reducing dev-prod drift
- Position B: Docker Compose to K8s via Kompose or Tilt bridges the gap; running Minikube for every developer laptop is wasteful
