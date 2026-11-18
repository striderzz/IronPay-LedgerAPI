// Shared helpers for the k6 scripts: test users with funded wallets, transfers.
import http from 'k6/http';
import { check } from 'k6';

export const BASE = __ENV.BASE_URL || 'http://localhost:8000';
const JSON_HEADERS = { 'Content-Type': 'application/json' };

let counter = 0;
// Unique per logical request. __VU and __ITER do not exist during setup(), hence the guards.
export function newKey() {
  counter += 1;
  const vu = typeof __VU !== 'undefined' ? __VU : 0;
  const iter = typeof __ITER !== 'undefined' ? __ITER : 0;
  return `k6-${vu}-${iter}-${counter}-${Date.now()}-${Math.floor(Math.random() * 1e9)}`;
}

// Register, log in, open a wallet and fund it, for `n` users. Runs once in setup().
export function setupUsers(n) {
  const run = `${Date.now() % 1e8}`;
  const users = [];
  for (let i = 0; i < n; i += 1) {
    const email = `load${run}_${i}@example.com`;
    const password = 'load-test-pass-1';
    let r = http.post(`${BASE}/auth/register`, JSON.stringify({ email, password }), { headers: JSON_HEADERS });
    check(r, { 'registered': (res) => res.status === 201 });
    r = http.post(`${BASE}/auth/token`, JSON.stringify({ email, password }), { headers: JSON_HEADERS });
    const token = r.json('access_token');
    const headers = { ...JSON_HEADERS, Authorization: `Bearer ${token}` };
    const handle = `l${run}u${i}@ironpay`;
    r = http.post(`${BASE}/accounts`, JSON.stringify({ handle }), { headers });
    const id = r.json('id');
    r = http.post(
      `${BASE}/deposits`,
      JSON.stringify({ to_account_id: id, amount_minor: 10000000 }), // 1,00,000 rupees
      { headers: { ...headers, 'Idempotency-Key': newKey() } },
    );
    check(r, { 'funded': (res) => res.status === 201 });
    users.push({ token, id, handle });
  }
  return users;
}

export function pickPair(users) {
  const a = Math.floor(Math.random() * users.length);
  let b = Math.floor(Math.random() * (users.length - 1));
  if (b >= a) b += 1;
  return [users[a], users[b]];
}

export function transferRequest(from, to, key) {
  const body = JSON.stringify({
    from_account_id: from.id,
    to_handle: to.handle,
    amount_minor: 100 + Math.floor(Math.random() * 9900), // 1 to 100 rupees
  });
  const params = {
    headers: { ...JSON_HEADERS, Authorization: `Bearer ${from.token}`, 'Idempotency-Key': key },
    tags: { name: 'transfer' },
  };
  return { body, params };
}
