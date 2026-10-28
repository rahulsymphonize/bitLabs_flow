from app.models import AuditLog


def log_action(
    db, actor, action, target_type=None, target_id=None, company_id=None,
    **meta,
):
    """Adds the row to the caller's transaction; the caller commits."""
    db.add(
        AuditLog(
            actor_id=actor.id if actor else None,
            company_id=company_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            meta=meta,
        )
    )
