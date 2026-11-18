"""Ledger invariant checks, used by scripts/check_ledger.py and by the tests.

Each check is one SQL query that returns the rows that break an invariant, so a clean
ledger returns zero rows everywhere.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

CHECKS: dict[str, str] = {
    # Money is never created or destroyed: across all accounts debits equal credits.
    "debits_equal_credits": """
        SELECT sum(amount_minor) FILTER (WHERE direction = 'debit')  AS debits,
               sum(amount_minor) FILTER (WHERE direction = 'credit') AS credits
        FROM ledger_entries
        HAVING coalesce(sum(amount_minor) FILTER (WHERE direction = 'debit'), 0)
            <> coalesce(sum(amount_minor) FILTER (WHERE direction = 'credit'), 0)
    """,
    # A completed transfer has exactly one debit on the sender and one credit on the
    # receiver, both for the transfer amount.
    "completed_transfer_entries": """
        SELECT t.id
        FROM transfers t
        LEFT JOIN ledger_entries d ON d.transfer_id = t.id AND d.direction = 'debit'
        LEFT JOIN ledger_entries c ON c.transfer_id = t.id AND c.direction = 'credit'
        WHERE t.status = 'completed'
          AND (d.id IS NULL OR c.id IS NULL
               OR d.account_id <> t.from_account_id OR c.account_id <> t.to_account_id
               OR d.amount_minor <> t.amount_minor OR c.amount_minor <> t.amount_minor)
    """,
    # A rejected transfer writes no entries.
    "rejected_transfer_has_entries": """
        SELECT t.id
        FROM transfers t JOIN ledger_entries e ON e.transfer_id = t.id
        WHERE t.status = 'rejected'
    """,
    # Wallets never go below zero (only the system funding account can).
    "negative_wallet_balance": """
        SELECT a.id, sum(CASE WHEN e.direction = 'credit' THEN e.amount_minor
                              ELSE -e.amount_minor END) AS balance
        FROM accounts a JOIN ledger_entries e ON e.account_id = a.id
        WHERE a.kind = 'wallet'
        GROUP BY a.id
        HAVING sum(CASE WHEN e.direction = 'credit' THEN e.amount_minor
                        ELSE -e.amount_minor END) < 0
    """,
}


def run_checks(session: Session) -> dict:
    """Return {"ok": bool, "violations": {check: count}, "totals": {...}}."""
    violations = {name: len(session.execute(text(sql)).all()) for name, sql in CHECKS.items()}
    totals = session.execute(
        text(
            """
            SELECT (SELECT count(*) FROM transfers WHERE status = 'completed') AS completed,
                   (SELECT count(*) FROM transfers WHERE status = 'rejected')  AS rejected,
                   (SELECT count(*) FROM ledger_entries)                       AS entries,
                   (SELECT coalesce(sum(amount_minor), 0) FROM ledger_entries
                     WHERE direction = 'debit')                                AS total_debits,
                   (SELECT coalesce(sum(amount_minor), 0) FROM ledger_entries
                     WHERE direction = 'credit')                               AS total_credits
            """
        )
    ).one()
    t = dict(totals._mapping)
    t["drift_minor"] = int(t["total_credits"]) - int(t["total_debits"])
    return {
        "ok": not any(violations.values()),
        "violations": violations,
        "totals": {k: int(v) for k, v in t.items()},
    }
