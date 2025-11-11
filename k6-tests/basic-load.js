import http from 'k6/http';
import { check, sleep } from 'k6';
import { Counter, Trend } from 'k6/metrics';

// Custom metrics
const externalApiDuration = new Trend('external_api_duration_ms');
const dbWriteDuration = new Trend('db_write_duration_ms');
const totalDuration = new Trend('total_request_duration_ms');
const successRate = new Counter('success_requests');
const errorRate = new Counter('error_requests');

// Test configuration
export const options = {
  stages: [
    { duration: '30s', target: 10 },  // Ramp up to 10 users
    { duration: '1m', target: 10 },   // Stay at 10 users
    { duration: '30s', target: 50 },  // Ramp up to 50 users
    { duration: '1m', target: 50 },   // Stay at 50 users
    { duration: '30s', target: 0 },   // Ramp down
  ],
  thresholds: {
    http_req_duration: ['p(95)<500'], // 95% of requests should be below 500ms
    http_req_failed: ['rate<0.1'],    // Error rate should be less than 10%
  },
};

export default function () {
  const url = __ENV.API_URL || 'http://host.docker.internal:7860/external-call';

  const response = http.post(url, null, {
    headers: { 'Content-Type': 'application/json' },
    tags: { name: 'ExternalCallEndpoint' },
  });

  // Check response
  const success = check(response, {
    'status is 200': (r) => r.status === 200,
    'has request_id': (r) => r.json('request_id') !== undefined,
    'has trace_id': (r) => r.json('trace_id') !== undefined,
  });

  if (success) {
    const body = response.json();

    // Record custom metrics
    if (body.external_api && body.external_api.duration_ms) {
      externalApiDuration.add(body.external_api.duration_ms);
    }
    if (body.database && body.database.write_duration_ms) {
      dbWriteDuration.add(body.database.write_duration_ms);
    }
    if (body.performance && body.performance.total_duration_ms) {
      totalDuration.add(body.performance.total_duration_ms);
    }

    successRate.add(1);
  } else {
    errorRate.add(1);
  }

  sleep(1); // Wait 1 second between requests
}