"""Transactional outbox and append-only audit log.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-18
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE outbox_events (
            id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            event_id     uuid NOT NULL UNIQUE DEFAULT gen_random_uuid(),
            event_type   text NOT NULL,
            aggregate_id uuid NOT NULL,
            payload      jsonb NOT NULL,
            attempts     int NOT NULL DEFAULT 0,
            last_error   text,
            created_at   timestamptz NOT NULL DEFAULT now(),
            published_at timestamptz
        );
        -- the relay only ever scans unpublished rows, in id order
        CREATE INDEX outbox_unpublished_idx ON outbox_events (id) WHERE published_at IS NULL;

        CREATE TABLE audit_log (
            id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            actor_id    uuid REFERENCES users(id),
            action      text NOT NULL,
            entity_type text NOT NULL,
            entity_id   text NOT NULL,
            request_id  text,
            ip          text,
            details     jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at  timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX audit_log_actor_idx ON audit_log (actor_id, created_at);

        CREATE FUNCTION reject_audit_change() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'audit_log is append-only';
        END;
        $$ LANGUAGE plpgsql;

        CREATE TRIGGER audit_log_append_only
            BEFORE UPDATE OR DELETE ON audit_log
            FOR EACH ROW EXECUTE FUNCTION reject_audit_change();
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE audit_log;
        DROP FUNCTION reject_audit_change();
        DROP TABLE outbox_events;
        """
    )
