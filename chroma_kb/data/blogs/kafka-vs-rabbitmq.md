# Kafka vs RabbitMQ

**Category**: Infrastructure
**Expected winner**: Kafka

## Analysis

Kafka is designed for high-throughput event streaming with replay, retention, and partitioning. RabbitMQ is a traditional message broker better for task distribution. For event-driven microservices at enterprise scale, Kafka's log-based architecture wins.

## Known Contradictions

### Complexity vs need
- Position A: Kafka requires ZooKeeper/KRaft and significant ops; RabbitMQ is simpler to operate
- Position B: Managed Kafka (Confluent Cloud) removes ops burden; the replay and retention features prevent data loss that RabbitMQ can't guarantee
