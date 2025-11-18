import http from 'k6/http';
import { check, sleep } from 'k6';

// Get test parameters from environment variables
const VUS = parseInt(__ENV.VUS || '50');           // Number of virtual users
const DURATION = __ENV.DURATION || '3m';           // Test duration
const RAMP_UP = __ENV.RAMP_UP || '1m';            // Ramp up time
const MOCK_DELAY = parseInt(__ENV.MOCK_DELAY || '0'); // Mock API delay in seconds

export const options = {
  stages: [
    { duration: RAMP_UP, target: VUS },     // Ramp up
    { duration: DURATION, target: VUS },    // Hold
    { duration: '30s', target: 0 },         // Ramp down
  ],
  thresholds: {
    http_req_duration: ['p(95)<500'],     // 95% under 10s
    http_req_failed: ['rate<0.3'],          // Less than 30% errors (allow some for stress tests)
  },
};

export default function () {
  // Build URL with optional mock delay
  const baseUrl = 'http://api:7860/external-call';
  const url = MOCK_DELAY > 0 ? `http://api:7860/mock-api?delay=${MOCK_DELAY}` : baseUrl;

  const response = http.post(baseUrl, null, {
    headers: { 'Content-Type': 'application/json' },
    timeout: '180s',
  });

  const success = check(response, {
    'status is 200': (r) => r.status === 200,
    'has correlation_id': (r) => {
      try {
        return r.json('correlation_id') !== undefined;
      } catch {
        return false;
      }
    },
  });

  if (!success) {
    console.log(`Failed: Status ${response.status} at ${new Date().toISOString()}`);
  }

  sleep(0.5);
}