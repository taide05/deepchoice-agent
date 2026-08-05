# gRPC vs WebSocket

**Category**: Backend Frameworks & API
**Expected winner**: context_dependent

## Analysis

gRPC wins for microservice-to-microservice communication (strong typing, streaming, multiplexing). WebSocket wins for browser-to-server real-time comms (native browser support, simpler for chat/notifications). The choice depends on client type.

## Known Contradictions

### Browser support
- Position A: gRPC-web bridges the gap but adds complexity
- Position B: WebSocket is natively supported in all browsers with zero additional infrastructure
