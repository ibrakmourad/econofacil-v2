"""Serviço de LGPD: consentimento, portabilidade e direito ao esquecimento."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import hash_password
from app.models.consent import Consent, ConsentPurpose
from app.models.refresh_token import RefreshToken
from app.models.user import User


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def get_consents(db: AsyncSession, user_id: uuid.UUID) -> list[Consent]:
    result = await db.execute(
        select(Consent).where(Consent.user_id == user_id)
    )
    return list(result.scalars().all())


async def set_consent(
    db: AsyncSession,
    user_id: uuid.UUID,
    purpose: ConsentPurpose,
    granted: bool,
    *,
    commit: bool = True,
) -> Consent:
    result = await db.execute(
        select(Consent).where(
            Consent.user_id == user_id, Consent.purpose == purpose
        )
    )
    consent = result.scalar_one_or_none()
    now = _utcnow()

    if consent is None:
        consent = Consent(
            user_id=user_id,
            purpose=purpose,
            granted=granted,
            terms_version=settings.TERMS_VERSION,
            granted_at=now if granted else None,
            revoked_at=None if granted else now,
        )
        db.add(consent)
    else:
        consent.granted = granted
        consent.terms_version = settings.TERMS_VERSION
        if granted:
            consent.granted_at = now
            consent.revoked_at = None
        else:
            consent.revoked_at = now

    if commit:
        await db.commit()
        await db.refresh(consent)
    else:
        await db.flush()
    return consent


async def export_user_data(db: AsyncSession, user: User) -> dict:
    """Monta o pacote de portabilidade (Art. 18 da LGPD)."""
    consents = await get_consents(db, user.id)
    sessions_result = await db.execute(
        select(RefreshToken).where(RefreshToken.user_id == user.id)
    )
    sessions = [
        {
            "created_at": s.created_at.isoformat(),
            "expires_at": s.expires_at.isoformat(),
            "revoked": s.revoked,
            "user_agent": s.user_agent,
        }
        for s in sessions_result.scalars().all()
    ]
    return {
        "user_id": user.id,
        "profile": {
            "email": user.email,
            "full_name": user.full_name,
            "role": user.role.value,
            "is_verified": user.is_verified,
            "created_at": user.created_at.isoformat(),
        },
        "consents": consents,
        "sessions": sessions,
        "generated_at": _utcnow(),
    }


async def anonymize_user(db: AsyncSession, user: User) -> None:
    """Direito ao esquecimento: remove os dados pessoais preservando a
    integridade referencial (ex.: histórico de pedidos agregado)."""
    anon_id = uuid.uuid4().hex[:12]
    user.email = f"anon_{anon_id}@removed.econofacil"
    user.full_name = "Usuário removido"
    # senha aleatória irrecuperável + conta inativa
    user.hashed_password = hash_password(uuid.uuid4().hex)
    user.is_active = False
    user.is_verified = False
    user.is_2fa_enabled = False
    user.totp_secret = None
    user.anonymized_at = _utcnow()

    # revoga sessões e remove consentimentos
    sessions_result = await db.execute(
        select(RefreshToken).where(RefreshToken.user_id == user.id)
    )
    for s in sessions_result.scalars().all():
        s.revoked = True

    consents_result = await db.execute(
        select(Consent).where(Consent.user_id == user.id)
    )
    for c in consents_result.scalars().all():
        await db.delete(c)

    await db.commit()
