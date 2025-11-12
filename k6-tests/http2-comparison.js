import http from 'k6/http';
import { check, sleep } from 'k6';
import { Trend } from 'k6/metrics';

// Metrics for HTTP/1.1 vs HTTP/2 comparison
const http1Duration = new Trend('http1_duration_ms');
const http2Duration = new Trend('http2_duration_ms');

export const options = {
  stages: [
    { duration: '1m', target: 20 },
    { duration: '2m', target: 20 },
    { duration: '1m', target: 0 },
  ],
  thresholds: {
    http_req_duration: ['p(95)<1000'],
  },
};

export default function () {
  const baseUrl = 'http://api:7860/external-call';

  // Test with current configuration
  const response = http.post(baseUrl, null, {
    headers: { 'Content-Type': 'application/json' },
    tags: { protocol: 'current' },
  });

  if (response.status === 200) {
    const body = response.json();
    if (body.performance && body.performance.total_duration_ms) {
      http1Duration.add(body.performance.total_duration_ms);
    }
  }

  check(response, {
    'status is 200': (r) => r.status === 200,
    'response time acceptable': (r) => r.timings.duration < 1000,
  });

  sleep(1);
}