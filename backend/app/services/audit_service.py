"""Serviço de auditoria — registra ações relevantes para a LGPD."""
from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog


async def log_action(
    db: AsyncSession,
    *,
    action: str,
    user_id: uuid.UUID | None = None,
    entity: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    details: dict | None = None,
    commit: bool = True,
) -> AuditLog:
    entry = AuditLog(
        user_id=user_id,
        action=action,
        entity=entity,
        ip_address=ip_address,
        user_agent=user_agent,
        details=details,
    )
    db.add(entry)
    if commit:
        await db.commit()
    else:
        await db.flush()
    return entry
