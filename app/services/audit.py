"""Append-only audit log: who did what, from where, under which request id.

Rows are written in the caller's transaction. A trigger rejects UPDATE and DELETE.
"""

import json
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.request_context import client_ip_var, request_id_var


def record(
    session: Session,
    *,
    actor_id: uuid.UUID | None,
    action: str,
    entity_type: str,
    entity_id: str,
    details: dict[str, Any] | None = None,
) -> None:
    session.execute(
        text(
            "INSERT INTO audit_log "
            "(actor_id, action, entity_type, entity_id, request_id, ip, details) "
            "VALUES (:actor, :action, :etype, :eid, :rid, :ip, CAST(:details AS jsonb))"
        ),
        {
            "actor": actor_id,
            "action": action,
            "etype": entity_type,
            "eid": entity_id,
            "rid": request_id_var.get(),
            "ip": client_ip_var.get(),
            "details": json.dumps(details or {}),
        },
    )
