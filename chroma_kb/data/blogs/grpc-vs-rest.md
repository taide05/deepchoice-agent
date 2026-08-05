# gRPC vs REST

**Category**: Backend Frameworks & API
**Expected winner**: gRPC

## Analysis

For internal microservice-to-microservice communication, gRPC wins on performance (Protocol Buffers, HTTP/2 multiplexing), type safety (generated stubs), and streaming support. REST is better for external/public APIs where human readability and browser access matter.

## Known Contradictions

### Debugging and tooling
- Position A: gRPC is harder to debug - can't just curl it like REST
- Position B: grpcurl and Postman gRPC support have closed the debugging gap; the performance gain is worth the tooling investment
