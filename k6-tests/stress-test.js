import http from 'k6/http';
import { check, sleep } from 'k6';

// Stress test - Push the system to its limits
export const options = {
  stages: [
    { duration: '2m', target: 100 },  // Ramp up to 100 users
    { duration: '5m', target: 100 },  // Stay at 100 users
    { duration: '2m', target: 200 },  // Push to 200 users
    { duration: '5m', target: 200 },  // Stay at 200 users
    { duration: '2m', target: 0 },    // Ramp down
  ],
  thresholds: {
    http_req_duration: ['p(99)<3000'], // 99% under 3s
    http_req_failed: ['rate<0.2'],     // Less than 20% errors
  },
};

export default function () {
  const url = 'http://api:7860/external-call';

  const response = http.post(url, null, {
    headers: { 'Content-Type': 'application/json' },
  });

  check(response, {
    'status is 200': (r) => r.status === 200,
    'response time OK': (r) => r.timings.duration < 3000,
  });

  sleep(0.1); // Short sleep to increase load
}