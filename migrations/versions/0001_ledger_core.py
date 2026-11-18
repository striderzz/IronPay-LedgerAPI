"""Ledger core: users, accounts, transfers, ledger entries.

Revision ID: 0001
Revises:
Create Date: 2026-11-18
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE users (
            id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            email         text NOT NULL UNIQUE,
            password_hash text NOT NULL,
            created_at    timestamptz NOT NULL DEFAULT now()
        );

        CREATE TABLE accounts (
            id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id    uuid REFERENCES users(id),
            handle     text NOT NULL UNIQUE CHECK (handle ~ '^[a-z0-9._-]{3,32}@ironpay$'),
            kind       text NOT NULL CHECK (kind IN ('wallet', 'system')),
            currency   char(3) NOT NULL DEFAULT 'INR',
            status     text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'frozen')),
            created_at timestamptz NOT NULL DEFAULT now(),
            -- wallets belong to a user; the system funding account belongs to nobody
            CHECK ((kind = 'system') = (user_id IS NULL))
        );
        CREATE INDEX accounts_user_id_idx ON accounts (user_id);

        CREATE TABLE transfers (
            id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            from_account_id uuid NOT NULL REFERENCES accounts(id),
            to_account_id   uuid NOT NULL REFERENCES accounts(id),
            amount_minor    bigint NOT NULL CHECK (amount_minor > 0),
            kind            text NOT NULL CHECK (kind IN ('transfer', 'deposit')),
            status          text NOT NULL CHECK (status IN ('completed', 'rejected')),
            reject_reason   text,
            note            text CHECK (length(note) <= 140),
            created_at      timestamptz NOT NULL DEFAULT now(),
            CHECK (from_account_id <> to_account_id),
            CHECK ((status = 'rejected') = (reject_reason IS NOT NULL))
        );
        CREATE INDEX transfers_from_idx ON transfers (from_account_id, created_at);
        CREATE INDEX transfers_to_idx ON transfers (to_account_id, created_at);

        CREATE TABLE ledger_entries (
            id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            transfer_id  uuid NOT NULL REFERENCES transfers(id),
            account_id   uuid NOT NULL REFERENCES accounts(id),
            direction    text NOT NULL CHECK (direction IN ('debit', 'credit')),
            amount_minor bigint NOT NULL CHECK (amount_minor > 0),
            created_at   timestamptz NOT NULL DEFAULT now(),
            -- at most one debit and one credit per transfer
            UNIQUE (transfer_id, direction)
        );
        -- balance sums and keyset pagination both read entries by account in id order
        CREATE INDEX ledger_entries_account_idx ON ledger_entries (account_id, id);

        -- Entries are append-only: corrections are new entries, never edits.
        CREATE FUNCTION reject_ledger_change() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'ledger_entries is append-only';
        END;
        $$ LANGUAGE plpgsql;

        CREATE TRIGGER ledger_entries_append_only
            BEFORE UPDATE OR DELETE ON ledger_entries
            FOR EACH ROW EXECUTE FUNCTION reject_ledger_change();

        -- The system funding account is the source of every deposit, so money is
        -- never created out of nothing: total debits always equal total credits.
        INSERT INTO accounts (handle, kind) VALUES ('funding@ironpay', 'system');
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE ledger_entries;
        DROP FUNCTION reject_ledger_change();
        DROP TABLE transfers;
        DROP TABLE accounts;
        DROP TABLE users;
        """
    )
