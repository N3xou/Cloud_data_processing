# Load Testing Results - Lab 5

## Test Configuration
- **Date**: YYYY-MM-DD
- **HTTP Client**: max_connections=50, keepalive=20 (from Lab 4)
- **VUs**: 50 virtual users
- **Duration**: 3 minutes at peak load
- **External API**: Mock API (no artificial delay)

## Results Summary

| Scenario                | Broker     | Max RPS | p50 Latency | p95 Latency | p99 Latency | Error Rate |
|-------------------------|-----------|---------|-------------|-------------|-------------|------------|
| Baseline (Lab 4)        | none      | 63      |      XX ms  |      XX ms  |      XX ms  | 0%         |
| Async Upstream (A)      | Kafka     | 150     |      XX ms  |      XX ms  |      XX ms  | 0.1%       |
| Async Upstream (A)      | RabbitMQ  | 110     |      XX ms  |      XX ms  |      XX ms  | 0%         |
| Async Downstream (B)    | Kafka     | 57      |      XX ms  |      XX ms  |      XX ms  | 0.1%       |
| Async Downstream (B)    | RabbitMQ  | 79      |      XX ms  |      XX ms  |      XX ms  | 0.1%       |

## Analysis

### Maximum RPS
**Winner**: [Scenario Name]

[Explanation of why this scenario achieved the highest RPS]

### Latency Comparison

**Async Upstream vs Baseline**:
- Async Upstream showed XX% faster response times
- This is because the API immediately returns 202 without waiting for External API or DB

**Async Downstream vs Baseline**:
- Async Downstream showed XX% improvement
- Client still waits for External API, but DB write is offloaded

**Kafka vs RabbitMQ**:
- Kafka: [observations]
- RabbitMQ: [observations]
- Difference: [analysis]

### Key Findings

1. **Fastest Client Response**: Async Upstream (Scenario A)
   - Achieves lowest latency from client perspective
   - Trade-off: Client doesn't know when processing completes

2. **Best Balance**: [Your choice]
   - Reasons: [...]

3. **Broker Comparison**:
   - [Your observations about Kafka vs RabbitMQ performance]

### Correlation ID Tracking

Successfully tracked requests end-to-end using correlation IDs:
- Visible in API logs
- Visible in Worker logs
- Linked to Tempo traces
- Searchable in Loki

See screenshot: `loki-tempo-correlation.png`

## Observations

### Worker Behavior
- Worker processing time: ~XX ms average
- Queue depth stayed at: [XX] messages
- No message loss detected

### System Behavior Under Load
- [Your observations]

## Recommendations

Based on these results, for a production system:
- Use [Scenario] when [conditions]
- Choose [Kafka/RabbitMQ] because [reasons]