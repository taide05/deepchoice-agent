# GitHub Actions vs Jenkins

**Category**: Deployment & Operations
**Expected winner**: GitHub Actions

## Analysis

For teams already on GitHub, GitHub Actions wins on integration, maintenance burden (no self-hosted server), and marketplace ecosystem. Jenkins still wins for complex pipelines with custom plugin requirements, air-gapped environments, or multi-repo orchestration that goes beyond GitHub's scope.

## Known Contradictions

### Vendor lock-in
- Position A: GitHub Actions YAML syntax is proprietary; migrating away from GitHub means rewriting all CI
- Position B: Jenkins' Groovy-based Jenkinsfile is also proprietary in practice; CI migration is always painful regardless of tool
