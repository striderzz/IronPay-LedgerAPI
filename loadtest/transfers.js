// POST /transfers at a fixed arrival rate between random funded wallets.
// Env: RATE (requests/sec), DURATION (e.g. 60s), USERS, OUT (summary JSON path).
import http from 'k6/http';
import { check } from 'k6';
import { BASE, newKey, pickPair, setupUsers, transferRequest } from './common.js';

const RATE = parseInt(__ENV.RATE || '50', 10);
const DURATION = __ENV.DURATION || '60s';
const USERS = parseInt(__ENV.USERS || '100', 10);

export const options = {
  setupTimeout: '300s',
  scenarios: {
    transfers: {
      executor: 'constant-arrival-rate',
      rate: RATE,
      timeUnit: '1s',
      duration: DURATION,
      preAllocatedVUs: Math.max(20, RATE),
      maxVUs: Math.max(50, RATE * 4),
    },
  },
  summaryTrendStats: ['avg', 'min', 'med', 'p(90)', 'p(95)', 'p(99)', 'max'],
  // Permissive thresholds only make k6 report the per-tag submetrics.
  thresholds: {
    'http_req_duration{name:transfer}': ['p(95)<60000'],
    'http_req_failed{name:transfer}': ['rate<1.01'],
    'http_reqs{name:transfer}': ['count>=0'],
  },
};

export function setup() {
  return { users: setupUsers(USERS) };
}

export default function (data) {
  const [from, to] = pickPair(data.users);
  const { body, params } = transferRequest(from, to, newKey());
  const r = http.post(`${BASE}/transfers`, body, params);
  check(r, { 'transfer 201': (res) => res.status === 201 });
}

export function handleSummary(data) {
  return { [__ENV.OUT || 'summary.json']: JSON.stringify(data, null, 2) };
}
