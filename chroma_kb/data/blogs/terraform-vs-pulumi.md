# Terraform vs Pulumi

**Category**: Deployment & Operations
**Expected winner**: context_dependent

## Analysis

Terraform wins on ecosystem maturity (more providers, modules, community). Pulumi wins for teams that prefer general-purpose languages over HCL. For a team with strong Python/TypeScript skills, Pulumi is better; for a traditional DevOps team, Terraform HCL is simpler.

## Known Contradictions

### HCL vs general-purpose languages
- Position A: HCL is declarative and cleaner for infrastructure definition
- Position B: General-purpose languages give you loops, functions, and abstractions that HCL can't match without complex workarounds
