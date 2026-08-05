# Modal vs AWS Lambda

**Category**: Deployment & Operations
**Expected winner**: Modal

## Analysis

Modal is purpose-built for Python/ML workloads with GPU support, longer timeouts (up to 1 hour), and simpler Python-native API. AWS Lambda has a 15-minute timeout, no GPU, and requires more infrastructure configuration. For ML inference, Modal wins decisively.

## Known Contradictions

### Vendor lock-in
- Position A: Modal is a single-vendor platform; Lambda is on AWS with massive ecosystem
- Position B: Modal deploys standard Docker images — migration is straightforward; the GPU support and 1-hour timeout enable use cases that Lambda simply can't handle
