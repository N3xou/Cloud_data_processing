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
    'http_req_duration': ['p(95)<2000'],  // Similar to baseline (waits for External API)
    'errors': ['rate<0.05'],
  },
  tags: {
    scenario: 'async-downstream',
    broker: BROKER,
    testid: __ENV.TEST_ID || `async-downstream-${BROKER}`,
  },
};

export default function () {
  const url = `http://api:7860/external/fetch/async-downstream?broker=${BROKER}`;
  const correlationId = `async-down-${BROKER}-${__VU}-${Date.now()}`;

  const params = {
    headers: {
      'Content-Type': 'application/json',
      'X-Correlation-ID': correlationId,
    },
    tags: {
      scenario: 'async-downstream',
      broker: BROKER,
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
    'has external_api result': (r) => {
      try {
        return r.json('external_api') !== undefined;
      } catch {
        return false;
      }
    },
    'db status is enqueued': (r) => {
      try {
        return r.json('database').status === 'enqueued';
      } catch {
        return false;
      }
    },
    'broker matches': (r) => {
      try {
        return r.json('database').broker === BROKER;
      } catch {
        return false;
      }
    },
  });

  errorRate.add(!success);
  requestDuration.add(duration);

  if (!success) {
    console.log(`[ASYNC-DOWN-${BROKER}] Failed: Status ${response.status}, Correlation: ${correlationId}`);
  }

  sleep(0.5);
}