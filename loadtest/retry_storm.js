// Retry storm: every logical transfer is sent 5 times with the same Idempotency-Key
// (3 sequential retries plus 2 parallel copies). The unique_keys counter is compared
// with the number of transfers in PostgreSQL afterwards; duplicates must be 0.
// Env: RATE (logical transfers/sec), DURATION, USERS, OUT.
import http from 'k6/http';
import { check } from 'k6';
import { Counter } from 'k6/metrics';
import { BASE, newKey, pickPair, setupUsers, transferRequest } from './common.js';

const RATE = parseInt(__ENV.RATE || '20', 10);
const DURATION = __ENV.DURATION || '60s';
const USERS = parseInt(__ENV.USERS || '100', 10);
const uniqueKeys = new Counter('unique_keys');
const sameAnswer = new Counter('replays_matching_first_response');

export const options = {
  setupTimeout: '300s',
  scenarios: {
    storm: {
      executor: 'constant-arrival-rate',
      rate: RATE,
      timeUnit: '1s',
      duration: DURATION,
      preAllocatedVUs: Math.max(20, RATE * 2),
      maxVUs: Math.max(50, RATE * 8),
    },
  },
  summaryTrendStats: ['avg', 'med', 'p(95)', 'p(99)', 'max'],
  thresholds: {
    'http_req_failed{name:transfer}': ['rate<1.01'],
    'http_reqs{name:transfer}': ['count>=0'],
    'http_req_duration{name:transfer}': ['p(95)<60000'],
  },
};

export function setup() {
  return { users: setupUsers(USERS) };
}

export default function (data) {
  const [from, to] = pickPair(data.users);
  const key = newKey();
  const { body, params } = transferRequest(from, to, key);
  uniqueKeys.add(1);

  const first = http.post(`${BASE}/transfers`, body, params);
  const id = first.status === 201 ? first.json('id') : null;
  const responses = [
    http.post(`${BASE}/transfers`, body, params),
    http.post(`${BASE}/transfers`, body, params),
    ...http.batch([
      ['POST', `${BASE}/transfers`, body, params],
      ['POST', `${BASE}/transfers`, body, params],
    ]),
  ];
  for (const r of responses) {
    if (r.status === first.status && (id === null || r.json('id') === id)) sameAnswer.add(1);
  }
  check(first, { 'first 201': (res) => res.status === 201 });
}

export function handleSummary(data) {
  return { [__ENV.OUT || 'storm.json']: JSON.stringify(data, null, 2) };
}
