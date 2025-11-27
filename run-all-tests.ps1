# Lab 5: Async Messaging Load Tests
# Runs all 5 test scenarios and saves results

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$resultsDir = "docs/messaging-load-tests"

Write-Host "=====================================" -ForegroundColor Cyan
Write-Host "  Lab 5: Async Messaging Tests" -ForegroundColor Cyan
Write-Host "  Timestamp: $timestamp" -ForegroundColor Cyan
Write-Host "=====================================" -ForegroundColor Cyan

# Ensure directory exists
New-Item -ItemType Directory -Force -Path $resultsDir | Out-Null

# Test 1: Baseline
Write-Host "`n=== Test 1: Baseline (No Messaging) ===" -ForegroundColor Green
docker exec cifar10_db psql -U postgres -d cifar10 -c "TRUNCATE external_api_calls;" | Out-Null

docker exec k6 k6 run `
  --out experimental-prometheus-rw `
  --env TEST_ID="baseline-$timestamp" `
  /scripts/baseline.js

Write-Host "Take screenshot: baseline-grafana.png" -ForegroundColor Yellow
Write-Host "Press Enter to continue..." -ForegroundColor Yellow
Read-Host

# Get baseline results
Write-Host "Baseline Results:" -ForegroundColor Cyan
docker exec cifar10_db psql -U postgres -d cifar10 -c "
SELECT
  COUNT(*) as requests,
  CAST(AVG(request_duration_ms) AS NUMERIC(10,2)) as avg_ms,
  CAST(PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY request_duration_ms) AS NUMERIC(10,2)) as p50_ms,
  CAST(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY request_duration_ms) AS NUMERIC(10,2)) as p95_ms,
  CAST(PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY request_duration_ms) AS NUMERIC(10,2)) as p99_ms
FROM external_api_calls;
"

# Test 2: Async Upstream - Kafka
Write-Host "`n=== Test 2: Async Upstream - Kafka ===" -ForegroundColor Green
docker exec cifar10_db psql -U postgres -d cifar10 -c "TRUNCATE external_api_calls;" | Out-Null

docker exec k6 k6 run `
  --out experimental-prometheus-rw `
  --env TEST_ID="async-upstream-kafka-$timestamp" `
  --env BROKER=kafka `
  /scripts/async-upstream.js

Write-Host "Wait for workers to process messages..." -ForegroundColor Yellow
Start-Sleep -Seconds 30

Write-Host "Take screenshot: async-upstream-kafka.png" -ForegroundColor Yellow
Read-Host "Press Enter to continue..."

# Test 3: Async Upstream - RabbitMQ
Write-Host "`n=== Test 3: Async Upstream - RabbitMQ ===" -ForegroundColor Green
docker exec cifar10_db psql -U postgres -d cifar10 -c "TRUNCATE external_api_calls;" | Out-Null

docker exec k6 k6 run `
  --out experimental-prometheus-rw `
  --env TEST_ID="async-upstream-rabbitmq-$timestamp" `
  --env BROKER=rabbitmq `
  /scripts/async-upstream.js

Start-Sleep -Seconds 30

Write-Host "Take screenshot: async-upstream-rabbitmq.png" -ForegroundColor Yellow
Read-Host "Press Enter to continue..."

# Test 4: Async Downstream - Kafka
Write-Host "`n=== Test 4: Async Downstream - Kafka ===" -ForegroundColor Green
docker exec cifar10_db psql -U postgres -d cifar10 -c "TRUNCATE external_api_calls;" | Out-Null

docker exec k6 k6 run `
  --out experimental-prometheus-rw `
  --env TEST_ID="async-downstream-kafka-$timestamp" `
  --env BROKER=kafka `
  /scripts/async-downstream.js

Start-Sleep -Seconds 30

Write-Host "Take screenshot: async-downstream-kafka.png" -ForegroundColor Yellow
Read-Host "Press Enter to continue..."

# Test 5: Async Downstream - RabbitMQ
Write-Host "`n=== Test 5: Async Downstream - RabbitMQ ===" -ForegroundColor Green
docker exec cifar10_db psql -U postgres -d cifar10 -c "TRUNCATE external_api_calls;" | Out-Null

docker exec k6 k6 run `
  --out experimental-prometheus-rw `
  --env TEST_ID="async-downstream-rabbitmq-$timestamp" `
  --env BROKER=rabbitmq `
  /scripts/async-downstream.js

Start-Sleep -Seconds 30

Write-Host "Take screenshot: async-downstream-rabbitmq.png" -ForegroundColor Yellow
Read-Host "Press Enter to continue..."

# Final summary
Write-Host "`n=====================================" -ForegroundColor Cyan
Write-Host "  All tests completed!" -ForegroundColor Cyan
Write-Host "=====================================" -ForegroundColor Cyan
Write-Host "Next steps:" -ForegroundColor Yellow
Write-Host "1. Check docs/messaging-load-tests/ for screenshots" -ForegroundColor Gray
Write-Host "2. Create RESULTS.md with comparison table" -ForegroundColor Gray
Write-Host "3. Add Loki + Tempo correlation screenshot" -ForegroundColor Gray