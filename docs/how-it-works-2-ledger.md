# How it works: ledger core (Phase 2)

## Tables (migration `0001_ledger_core`)

- `users`, `accounts` (wallets with a UPI-style handle such as `asha@ironpay`, plus one `system` funding account), `transfers` and `ledger_entries`.
- Money is `bigint` paise. `CHECK` constraints reject non-positive amounts, transfers to the same account, unknown kinds and directions, and a wallet without an owner.
- `UNIQUE (transfer_id, direction)` allows at most one debit and one credit per transfer.
- A trigger makes `ledger_entries` append-only: `UPDATE` and `DELETE` raise an error. Corrections are new entries.

## One helper for every money movement

`app/services/ledger.py::post_transfer` is the only code that writes entries:

1. Validate the amount and that the two accounts differ.
2. Lock both account rows with `SELECT ... FOR UPDATE`, one statement per row, in ascending id order. Every transaction takes the same order, so A to B and B to A cannot deadlock.
3. While holding the lock, compute the sender's balance as `sum(credits) - sum(debits)`. A concurrent transfer on the same wallet waits on the lock and, under `READ COMMITTED`, its next statement sees the entries the first one committed.
4. If the balance is too low (or an account is frozen), record a `rejected` transfer with a reason and write no entries. Otherwise record a `completed` transfer plus one debit and one credit.

The route commits, so the transfer row and both entries land together or not at all.

Deposits use the same helper, moving money from the system funding account, so money is never created out of nothing.

## Invariant checker

`app/services/checker.py` runs one SQL query per invariant and counts the rows that break it:

- total debits equal total credits
- every completed transfer has the right debit and credit
- rejected transfers have no entries
- no wallet is negative

`python -m scripts.check_ledger` prints the JSON report and exits `1` on any violation.

## Tests (real PostgreSQL)

- **Double spend:** a wallet holds 100 rupees and 50 threads send 10 rupees at the same instant (a barrier releases them together), each on its own connection. Exactly 10 succeed and 40 are rejected; the wallet ends at 0 and the checker reports no drift.
- **Opposite directions:** 40 parallel transfers alternating A to B and B to A all complete with no deadlock, and the total is conserved.
- **Rules:** append-only trigger, `CHECK` constraints, rejection paths, and a deliberately broken ledger that the checker must flag.
- **HTTP flow:** register, open wallets, deposit, transfer by handle, the 422 for insufficient funds, keyset pagination of entry history, and the 404/409/422 errors.
