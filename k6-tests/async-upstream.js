import http from 'k6/http';
import { check, sleep } from 'k6';
import { Rate, Trend } from 'k6/metrics';

// Custom metrics
const errorRate = new Rate('errors');
const requestDuration = new Trend('request_duration');

// Get broker from environment (kafka or rabbitmq)
const BROKER = __ENV.BROKER || 'kafka';

export const options = {
  stages: [
    { duration: '1m', target: 50 },
    { duration: '3m', target: 50 },
    { duration: '30s', target: 0 },
  ],
  thresholds: {
    'http_req_duration': ['p(95)<500'],  // Should be fast (just enqueues)
    'errors': ['rate<0.05'],
  },
  tags: {
    scenario: 'async-upstream',
    broker: BROKER,
    testid: __ENV.TEST_ID || `async-upstream-${BROKER}`,
  },
};

export default function () {
  const url = `http://api:7860/external/fetch/async-upstream?broker=${BROKER}`;
  const correlationId = `async-up-${BROKER}-${__VU}-${Date.now()}`;

  const params = {
    headers: {
      'Content-Type': 'application/json',
      'X-Correlation-ID': correlationId,
    },
    tags: {
      scenario: 'async-upstream',
      broker: BROKER,
    },
  };

  const startTime = Date.now();
  const response = http.post(url, null, params);
  const duration = Date.now() - startTime;

  const success = check(response, {
    'status is 202': (r) => r.status === 202,  // Expect 202 Accepted
    'has correlation_id': (r) => {
      try {
        return r.json('correlation_id') !== undefined;
      } catch {
        return false;
      }
    },
    'has status accepted': (r) => {
      try {
        return r.json('status') === 'accepted';
      } catch {
        return false;
      }
    },
    'broker matches': (r) => {
      try {
        return r.json('broker') === BROKER;
      } catch {
        return false;
      }
    },
  });

  errorRate.add(!success);
  requestDuration.add(duration);

  if (!success) {
    console.log(`[ASYNC-UP-${BROKER}] Failed: Status ${response.status}, Correlation: ${correlationId}`);
  }

  sleep(0.5);
}