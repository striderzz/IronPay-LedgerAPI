# IronPay LedgerAPI: interview prep

Companion to [README.md](README.md). The core (phases 1 to 6) is built; numbers quoted here come from the runs saved in `docs/results/`. The overview, system design and workflow diagrams are in [INFO.md](INFO.md).

---

## Pitch

### 30-second pitch

I built IronPay, a small UPI-style payments API in FastAPI and PostgreSQL. It focuses on the three things a payments core has to get right: money is never created or lost, because every transfer writes balanced debit and credit entries in a double-entry ledger; a payment is never applied twice, because transfers take an Idempotency-Key; and parallel requests cannot overdraw a wallet, because account rows are locked with SELECT FOR UPDATE. I prove it with a concurrent double-spend test and a ledger invariant checker that run in CI against real Postgres and Redis, and with k6 load tests: on a 4-vCPU GitHub Actions runner it sustained 200 transfers a second, p95 was 51 ms at 100 a second, and a retry storm of 6,005 requests created zero duplicate transfers.

### 2-minute walkthrough

IronPay has users, wallets with UPI-style handles, and one system funding account. Money enters a wallet through a deposit, which is just a transfer from the funding account, so the total across all accounts always sums to zero.

When a client calls `POST /transfers`, the request goes through JWT auth and a Redis token bucket rate limiter. Then the transfer service opens a single Postgres transaction. First it inserts the idempotency key with a hash of the request body. If the key already exists with the same body, I return the stored response, so a retry after a timeout never moves money twice. Next I lock both account rows with SELECT FOR UPDATE, always in id order so two opposite transfers cannot deadlock. While holding the lock I compute the sender's balance from ledger entries. If there is enough money, I write the transfer row, one debit entry and one credit entry, an outbox event and an audit row, and store the response against the idempotency key. Then I commit. If anything fails, the whole thing rolls back.

Balances are never stored and edited; they are derived from entries. That means there is no balance column that can drift from history.

A separate relay worker reads the outbox table with SKIP LOCKED and publishes events to a Redis Stream. That avoids the dual-write problem where the database commits but the event is lost, or the reverse.

For testing, the key test funds a wallet with 100 rupees and fires 50 concurrent 10-rupee transfers from separate connections. Exactly 10 must succeed and the balance must end at zero. After every load test, an invariant checker confirms that debits equal credits across the whole ledger. k6 gives me p50 and p95 latency and the throughput where errors start. Everything runs with one `docker compose up`, and GitHub Actions runs lint, unit and integration tests against real Postgres and Redis on every push.

---

## Interview questions with answers

### Project overview

**1. What is IronPay in one sentence?**
A small payments API that moves money between wallets using a double-entry ledger, with idempotent transfers and row locking so retries and concurrent requests cannot create, lose or double-spend money.

**2. Why build a ledger instead of a balance column?**
A balance column updated in place loses history: if it is ever wrong, you cannot tell why. With a ledger, every movement is an immutable pair of entries, the balance is a sum over them, and any number can be traced to the transfers that produced it. It also gives a cheap global check: total debits must equal total credits.

**3. What was the hardest part?**
Getting idempotency and concurrency right together. A retry can arrive while the first request is still running, and two different transfers can hit the same wallet at once. Putting the idempotency key insert, the row locks and the ledger writes in one transaction made both cases fall out of Postgres semantics instead of application-level coordination.

**4. How do you know it is correct?**
Three layers. Integration tests against real Postgres check each rule. A concurrent double-spend test fires parallel transfers at one wallet and asserts the exact number of successes and a final balance of zero. After every test run and load test, an invariant checker confirms that debits equal credits per transfer and globally, and that no wallet is negative.

### Design decisions and trade-offs

**5. Why store money as integer paise?**
Floating point cannot represent values like 0.1 exactly, so sums drift. Integer minor units in a `BIGINT` are exact and fast. `NUMERIC` would also be exact, but integers make the arithmetic and the API (`amount_minor`) unambiguous and match what payment providers such as Stripe expose.

**6. Pessimistic or optimistic locking, and why?**
I used pessimistic locking with `SELECT ... FOR UPDATE`. Wallets in a payments system see real contention, and under optimistic locking each conflict means a failed update and a retry of the whole transaction, which wastes work and adds tail latency. Optimistic versioning is better when conflicts are rare and transactions are long. It is a stretch goal to build both and compare them under the same k6 load.

**7. How do you avoid deadlocks?**
Every transfer locks both account rows in ascending id order. A deadlock needs two transactions waiting on each other in a cycle, and a global lock order makes a cycle impossible. Postgres would still detect a deadlock and abort one transaction with `40P01`, but with ordered locks that should never happen, and a test with opposite transfers (A to B and B to A in parallel) checks it.

**8. Why READ COMMITTED and not SERIALIZABLE?**
The row locks already serialize everything that touches one wallet, so `READ COMMITTED` plus explicit locks is enough and is the Postgres default. `SERIALIZABLE` would also be correct, but it aborts transactions with `40001` under contention, so every write path needs a retry loop. Explicit locks make the critical section visible in the code, which is easier to explain and debug.

**9. Why are balances derived from entries if summing is slower?**
Correctness first: there is no second copy of the truth to drift. With an index on `(account_id)` the sum is cheap for the data sizes here. At larger scale I would add a cached balance column updated in the same transaction, or periodic balance snapshots plus a sum of newer entries, and keep the invariant checker comparing them.

**10. Why keep idempotency keys in Postgres and not Redis?**
The key and the transfer must commit or roll back together. If the key lived in Redis, a crash between writing the transfer and writing the key would let a retry create a second transfer. In Postgres they share one transaction. Redis could be added as a read-through cache for fast replays, but it would not be the source of truth.

**11. What happens if two requests with the same Idempotency-Key arrive at the same time?**
Both try to insert the key inside their transaction. The second insert conflicts with the first, uncommitted row and waits on the unique index. When the first commits, the second sees the conflict, reads the stored response and returns it. If the first rolls back, the second proceeds as a new request. No in-progress state or extra locking is needed.

**12. Why use an outbox instead of publishing the event after commit?**
Publishing after commit is a dual write: if the process crashes between commit and publish, the event is lost; if you publish before commit and the commit fails, consumers see a payment that never happened. The outbox row is written in the same transaction as the entries, so it exists if and only if the transfer does. A relay publishes it later, at least once.

**13. Why JWT and not sessions?**
The API is stateless and can run as several replicas behind a load balancer without shared session storage. The downside is that a token cannot be revoked before it expires, so access tokens last 15 minutes. Refresh tokens and a Redis deny list for logout are possible extensions.

**14. Why sync SQLAlchemy instead of async?**
The work per request is a short database transaction, so the database is the bottleneck, not the Python thread. Sync code with a thread pool is easier to read and debug, and lock behavior is easier to reason about. Async would help with many slow external calls, which matters if the FraudSight fraud call is added.

### Deep dives per tool

**15. How does FastAPI dependency injection work in this project?**
Routes declare `Depends(get_session)`, `Depends(current_user)` and `Depends(rate_limit)`. FastAPI resolves them per request, and dependencies that `yield` run cleanup after the response, which is where the session is closed. Tests override dependencies with `app.dependency_overrides` to point at the test database.

**16. What exactly does SELECT FOR UPDATE lock, and what does it not block?**
It takes a row-level lock on the selected rows that blocks other `FOR UPDATE`, `FOR SHARE`, `UPDATE` and `DELETE` on those rows until the transaction ends. Plain `SELECT` statements are not blocked because Postgres uses MVCC; they see the last committed version. That is why the balance check must happen after taking the lock, inside the same transaction.

**17. How does the outbox relay avoid two workers sending the same event?**
It selects a batch with `WHERE published_at IS NULL ORDER BY id LIMIT 100 FOR UPDATE SKIP LOCKED`. Rows locked by one worker are skipped by another, so workers split the batch instead of blocking. If a worker crashes after publishing but before marking the row, the event is sent again, which is why consumers deduplicate on `event_id`.

**18. How does the Redis token bucket work, and why Lua?**
Each user has a hash with tokens and a last-refill timestamp. On a request, the script refills tokens based on elapsed time up to the bucket size, then takes one if available, and sets a TTL. Running it as one Lua script makes the read-modify-write atomic, so two parallel requests cannot both take the last token. If no token is left the API returns `429` with `Retry-After`.

**19. How do Alembic migrations run, and what would make one unsafe in production?**
`alembic upgrade head` runs in CI before tests and in the container before the API starts. Unsafe migrations are ones that take long locks on big tables, such as adding a column with a volatile default (which rewrites the whole table), adding an index without `CONCURRENTLY`, or renaming a column the running code still reads. The safe pattern is expand, migrate data, then contract across separate deploys.

**20. How do you write the concurrent double-spend test in pytest?**
A fixture creates a wallet and deposits 100 rupees. The test uses a `ThreadPoolExecutor` with 50 workers, each with its own session or HTTP client, all sending a 10-rupee transfer with a unique Idempotency-Key, released together by a barrier. It asserts exactly 10 completed and 40 rejected transfers, a final balance of zero, and a clean invariant check.

**21. How do you keep integration tests isolated?**
A session-scoped fixture starts from a migrated database. Normal tests run inside a transaction that is rolled back at the end. Concurrency tests cannot share one transaction, so they use committed data and truncate the tables afterward. In CI, Postgres and Redis run as service containers.

**22. What do the k6 scenarios measure?**
A `constant-arrival-rate` scenario sends transfers at a fixed rate to get p50 and p95 latency without coordinated omission. A `ramping-arrival-rate` scenario raises the rate until the error rate passes 1% or p95 passes the threshold, which gives max transfers per second. A retry scenario resends each request with the same key to check zero duplicates. Thresholds make the run fail if limits are crossed.

**23. How does Pydantic protect the ledger?**
`amount_minor` is `Annotated[int, Field(gt=0, le=MAX_TRANSFER_MINOR)]`, so zero, negative and absurd amounts never reach the service. `extra="forbid"` rejects unknown fields, which catches client typos. Response models are separate from DB models, so internal fields are never returned. The database repeats the key rules as `CHECK` constraints in case code changes later.

**24. How is the audit log made append-only?**
A Postgres trigger on `audit_log` raises an exception on `UPDATE` or `DELETE`. Rows for money movements are written in the same transaction as the transfer, so there is no transfer without an audit record. In production I would also give the app's database role only `INSERT` and `SELECT` on that table.

### Scaling and failure modes

**25. What happens if the API process crashes in the middle of a transfer?**
The transaction never commits, so Postgres rolls it back: no entries, no outbox row, no idempotency record. The client sees a timeout and retries with the same key, which is processed as new. If the crash happened after commit but before the response, the retry finds the key and gets the stored response.

**26. What if Redis goes down?**
The rate limiter fails open and logs a warning, because correctness does not depend on it. The outbox relay cannot publish, so events pile up in the outbox table and are sent when Redis returns. No money state is lost, since all of it is in Postgres. I would alert on outbox lag.

**27. A merchant wallet receives thousands of payments per second. What breaks?**
Every transfer locks both rows, so all payments to that merchant serialize on one row lock and latency grows. Credits cannot overdraw an account, so one fix is to lock only the debited account and take no lock on the receiver. Others are splitting the merchant into several sub-accounts and summing them, or batching credits.

**28. How would you scale to 10x traffic?**
First measure where time goes. Likely steps: tune the connection pool and add PgBouncer, run several API replicas, add a cached balance column so balance reads do not scan entries, move balance and history reads to a read replica, and partition `ledger_entries` by time. Beyond that, shard accounts by id so each shard owns its wallets, with cross-shard transfers handled through a saga.

**29. The outbox relay is down for an hour. What happens?**
Transfers keep working because the relay is not on the request path. The outbox table grows, and consumers see events late. When the relay restarts it drains the backlog in order of id. I would monitor the age of the oldest unpublished row and alert on it.

**30. How long do you keep idempotency keys, and why does it matter?**
24 hours, which covers realistic client retry windows. A periodic job deletes expired keys so the table and its index stay small. If keys were kept forever the table would grow without bound; if kept too briefly, a slow retry could create a duplicate.

### Debugging scenarios

**31. p95 latency on POST /transfers jumped after a deploy. What do you check?**
Compare k6 runs before and after to confirm it. Then look at Postgres: `pg_stat_activity` for sessions waiting on locks, `pg_stat_statements` for slow queries, and `EXPLAIN ANALYZE` on the balance sum to check it still uses the `(account_id)` index. Then check pool usage, since pool waits look like slow queries from the app side, and finally the Redis call latency.

**32. You see deadlock errors in the logs. What happened?**
Some code path is taking locks in a different order, for example a new endpoint that locks the receiver first, or a transaction that touches accounts and then another table that another path touches first. I would find the two statements from the Postgres deadlock log, which lists both, and route all locking through one helper that sorts ids.

**33. The invariant checker reports balance drift. How do you investigate?**
Find which check fails: a transfer with unbalanced entries, a negative wallet, or a global debit-credit mismatch. Unbalanced transfers point to code that writes entries outside the shared helper or to a missing transaction boundary. I would add a deferred constraint or a check in the helper so it cannot recur, and fix the data with compensating entries rather than edits.

**34. Clients report 422 "key reused with a different request" spikes.**
Usually a client generates one key per session or per screen instead of per payment attempt, or it changes the body on retry (for example adding a timestamp). I would check the logs for the key and both request hashes, confirm which field differs, and fix the client. If the body is reordered JSON, the server should canonicalize it before hashing.

**35. The double-spend test passes locally but is flaky in CI.**
Likely causes are shared state between tests, too few database connections for the thread pool so some requests time out, or the test not waiting for all futures before asserting. I would make the pool size at least the worker count, add a barrier so requests really start together, assert on the exact counts, and print the transfer statuses on failure.

**36. Requests hang under load and then time out with no database errors.**
That is usually connection pool exhaustion: every worker thread is waiting for a connection, often because some code path holds a session too long or leaks one. Check pool metrics and `pg_stat_activity` for idle-in-transaction sessions. Fixes are to keep transactions short, never call slow external services inside one, and set pool timeouts so the failure is fast and visible.

### Behavioral (STAR outlines)

Fill the blanks with real outcomes after each phase ships.

**37. Tell me about a hard bug you found.**
- Situation: the first CI run of the ledger tests failed 14 tests with a foreign key violation: ledger entries were being inserted before their transfer row.
- Task: find why, without weakening the constraint.
- Action: the models had foreign keys but no ORM `relationship()`, so SQLAlchemy's unit of work had no reason to order the two INSERTs. I flush the transfer row explicitly before adding its entries and left a comment explaining why. Running the integration tests against a real Postgres in CI is what caught it; a mocked database would not have.
- Result: all 19 tests at that phase passed, including the 50-thread double-spend test (exactly 10 of 50 transfers succeed, drift 0).

**38. Tell me about a trade-off you made.**
- Situation: choosing between pessimistic and optimistic locking for transfers.
- Task: pick one that is correct under contention and that I can defend.
- Action: chose `SELECT FOR UPDATE` taken in ascending id order, with the balance summed from entries while the lock is held; an optimistic variant stays a stretch-goal benchmark.
- Result: the opposite-direction test (A to B and B to A in parallel) never deadlocks, and the load test held 200 transfers/s with p95 51 ms at 100/s on a shared 4-vCPU runner.

**39. Tell me about a measurement you got wrong at first.**
- Situation: my first load-test summary said the API managed only half the target rate at every step.
- Task: work out whether the API or the measurement was wrong.
- Action: k6's built-in `rate` averages over the whole run, including the slow `setup()` that registers 200 users with Argon2. I recorded each scenario's own duration and computed throughput as requests divided by that. I also found that overloading at 300 to 800/s left a backlog that broke the next test, so the step test now stops at the first failing rate and cools down between steps.
- Result: the corrected run showed 100/s with 0 errors and a max of 200/s, and the retry storm ran clean with 0 duplicates.

**40. Tell me about learning something new quickly.**
- Situation: I had used Postgres as a store but not its locking model.
- Task: understand isolation levels and row locks well enough to prove correctness.
- Action: read the Postgres docs on concurrency control, wrote the race as a test (50 threads behind a barrier, each on its own connection) and kept it in CI.
- Result: the test passes on every push; the invariant checker reports 0 drift after every load run.

---

## Resume bullets

Numbers from `docs/results/` (load test: GitHub Actions run 44235971697, one 4-vCPU runner).

- Built a UPI-style payments API in **FastAPI** and **PostgreSQL** with a **double-entry ledger** and **idempotent transfers**, sustaining **200 transfers/sec** (p95 **51 ms** at 100/sec) under **k6** load with **0 duplicate transfers** across a **6,005-request** retry storm
- Prevented double-spends with ordered **SELECT FOR UPDATE** row locks, verified by a **50-thread** concurrency test (exactly 10 of 50 transfers succeed) and a ledger invariant checker showing **0 drift** after load
- Added **JWT** auth, a **Redis** Lua token bucket, a **transactional outbox** to Redis Streams and an append-only audit log; **97%** coverage from **51 pytest** tests against real Postgres and Redis in **GitHub Actions**

---
