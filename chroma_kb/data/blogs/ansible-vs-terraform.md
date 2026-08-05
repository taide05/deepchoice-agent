# Ansible vs Terraform

**Category**: Deployment & Operations
**Expected winner**: context_dependent

## Analysis

These are complementary, not competing. Terraform provisions infrastructure (VMs, networks, databases). Ansible configures servers (install packages, manage configs, deploy apps). Most teams use both: Terraform for provisioning, Ansible for configuration.

## Known Contradictions

### Terraform provisioners vs Ansible
- Position A: Terraform can configure servers with provisioners, replacing Ansible
- Position B: Terraform provisioners are intentionally limited and break idempotency — HashiCorp themselves recommend using a dedicated config management tool
