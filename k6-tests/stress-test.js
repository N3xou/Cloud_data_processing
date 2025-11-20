import http from 'k6/http';
import { check, sleep } from 'k6';

// Stress test to find breaking point
// Starts at 50 VUs and increases gradually to 400
export const options = {
  stages: [
    { duration: '1m', target: 50 },   // Increase to 200
    { duration: '1m', target: 50 },   // Hold at 200
    { duration: '1m', target: 150 },   // Increase to 200
    { duration: '1m', target: 150 },   // Hold at 200
    { duration: '1m', target: 250 },   // Increase to 250
    { duration: '1m', target: 250 },   // Hold at 250
    { duration: '1m', target: 350 },   // Push to 350
    { duration: '1m', target: 350 },   // Hold at 350
    { duration: '1m', target: 0 },     // Ramp down
  ],
  thresholds: {
    http_req_failed: ['rate<0.5'],      // Allow up to 50% errors (finding breaking point)
    http_req_duration: ['p(99)<10000'], // 99% under 10 seconds
  },
};

export default function () {
  const url = __ENV.API_URL || 'http://host.docker.internal:7860/external-call';

  const response = http.post(url, null, {
    headers: { 'Content-Type': 'application/json' },
    timeout: '180s',
    idleConnectionTimeout: '0s'
  });

  const success = check(response, {
    'status is 200': (r) => r.status === 200,
    'status not 500': (r) => r.status !== 500,
    'status not timeout': (r) => r.status !== 0,
  });

  if (!success) {
    console.log(`[VU ${__VU}] Failed - Status: ${response.status}, Time: ${new Date().toISOString()}`);
  }

  //sleep(0.1); // Short sleep to maximize load
}