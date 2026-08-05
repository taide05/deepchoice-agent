# JWT vs Session-based Auth

**Category**: Backend Frameworks & API
**Expected winner**: JWT

## Analysis

JWT enables stateless auth which scales horizontally without shared session storage. Session-based auth is simpler for monoliths but requires Redis/DB for session sharing across instances. For REST API at scale, JWT + refresh tokens is the modern standard.

## Known Contradictions

### Token revocation
- Position A: JWT can't be revoked before expiry, which is a security risk
- Position B: Short-lived access tokens + refresh token rotation solves revocation; the stateless scaling benefit outweighs the revocation complexity
