"""Idempotency keys for transfers and deposits.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-18
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE idempotency_keys (
            user_id         uuid NOT NULL REFERENCES users(id),
            key             text NOT NULL CHECK (length(key) BETWEEN 1 AND 255),
            request_hash    text NOT NULL,
            response_status int,
            response_body   jsonb,
            created_at      timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (user_id, key)
        );
        -- lets a cleanup job delete expired keys without a full scan
        CREATE INDEX idempotency_keys_created_idx ON idempotency_keys (created_at);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE idempotency_keys")
