import http from 'k6/http';
import { check, sleep } from 'k6';
import { Rate, Trend } from 'k6/metrics';

// Custom metrics
const errorRate = new Rate('errors');
const requestDuration = new Trend('request_duration');

export const options = {
  stages: [
    { duration: '1m', target: 50 },   // Ramp up to 50 VUs
    { duration: '3m', target: 50 },   // Stay at 50 VUs
    { duration: '30s', target: 0 },   // Ramp down
  ],
  thresholds: {
    'http_req_duration': ['p(95)<2000'],  // 95% under 2s
    'errors': ['rate<0.05'],               // Less than 5% errors
  },
  tags: {
    scenario: 'baseline',
    broker: 'none',
    testid: __ENV.TEST_ID || 'baseline-test',
  },
};

export default function () {
  const url = 'http://api:7860/external-call';
  const correlationId = `baseline-${__VU}-${Date.now()}`;

  const params = {
    headers: {
      'Content-Type': 'application/json',
      'X-Correlation-ID': correlationId,
    },
    tags: {
      scenario: 'baseline',
      broker: 'none',
    },
  };

  const startTime = Date.now();
  const response = http.post(url, null, params);
  const duration = Date.now() - startTime;

  const success = check(response, {
    'status is 200': (r) => r.status === 200,
    'has correlation_id': (r) => {
      try {
        return r.json('correlation_id') !== undefined;
      } catch {
        return false;
      }
    },
    'has trace_id': (r) => {
      try {
        return r.json('trace_id') !== undefined;
      } catch {
        return false;
      }
    },
  });

  errorRate.add(!success);
  requestDuration.add(duration);

  if (!success) {
    console.log(`[BASELINE] Failed: Status ${response.status}, Correlation: ${correlationId}`);
  }

  sleep(0.5);
}