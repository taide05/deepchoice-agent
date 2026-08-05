# Caddy vs Nginx

**Category**: Deployment & Operations
**Expected winner**: Caddy

## Analysis

Caddy has automatic HTTPS, simpler configuration, and native Docker/container support. Nginx is more battle-tested at extreme scale but for typical containerized deployments, Caddy's zero-config TLS is a decisive advantage.

## Known Contradictions

### Performance at scale
- Position A: Nginx consistently outperforms Caddy at 100K+ concurrent connections
- Position B: If you're at 100K concurrent connections, you can afford to switch proxies — Caddy's TLS automation saves more engineer-hours at normal scale
