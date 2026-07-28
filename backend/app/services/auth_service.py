"""Serviço de autenticação: tokens, refresh, 2FA e reset de senha."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pyotp
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import (
    create_access_token,
    generate_refresh_token,
    hash_token,
)
from app.models.refresh_token import RefreshToken
from app.models.user import User


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# Emissão de tokens
# --------------------------------------------------------------------------- #
async def issue_tokens(
    db: AsyncSession,
    user: User,
    *,
    user_agent: str | None = None,
    ip_address: str | None = None,
    commit: bool = True,
) -> tuple[str, str]:
    """Gera um access token (JWT) e um refresh token (opaco)."""
    access = create_access_token(subject=str(user.id), role=user.role.value)

    raw_refresh = generate_refresh_token()
    record = RefreshToken(
        user_id=user.id,
        token_hash=hash_token(raw_refresh),
        expires_at=_utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        user_agent=(user_agent or "")[:255] or None,
        ip_address=ip_address,
    )
    db.add(record)
    if commit:
        await db.commit()
    else:
        await db.flush()
    return access, raw_refresh


async def rotate_refresh_token(
    db: AsyncSession, raw_refresh: str
) -> tuple[str, str] | None:
    """Valida um refresh token, revoga-o e emite um novo par (rotação)."""
    token_hash = hash_token(raw_refresh)
    result = await db.execute(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    )
    record = result.scalar_one_or_none()

    if record is None or record.revoked:
        return None
    # SQLite devolve datetime naive; Postgres devolve aware. Normalizamos.
    expires_at = record.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= _utcnow():
        return None

    user = await db.get(User, record.user_id)
    if user is None or not user.is_active:
        return None

    record.revoked = True
    access, new_refresh = await issue_tokens(db, user, commit=False)
    await db.commit()
    return access, new_refresh


async def revoke_refresh_token(db: AsyncSession, raw_refresh: str) -> bool:
    token_hash = hash_token(raw_refresh)
    result = await db.execute(
        update(RefreshToken)
        .where(RefreshToken.token_hash == token_hash, RefreshToken.revoked.is_(False))
        .values(revoked=True)
    )
    await db.commit()
    return result.rowcount > 0


async def revoke_all_user_tokens(db: AsyncSession, user_id: uuid.UUID) -> None:
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked.is_(False))
        .values(revoked=True)
    )
    await db.commit()


# --------------------------------------------------------------------------- #
# 2FA (TOTP)
# --------------------------------------------------------------------------- #
def generate_totp_secret() -> str:
    return pyotp.random_base32()


def build_otpauth_uri(secret: str, email: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(
        name=email, issuer_name=settings.TOTP_ISSUER
    )


def verify_totp(secret: str, code: str) -> bool:
    if not secret or not code:
        return False
    return pyotp.TOTP(secret).verify(code, valid_window=1)
