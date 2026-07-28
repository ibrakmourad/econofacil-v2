"""Serviço de usuários: criação, consulta e atualização."""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models.user import User, UserRole


async def get_by_email(db: AsyncSession, email: str) -> User | None:
    result = await db.execute(select(User).where(User.email == email.lower()))
    return result.scalar_one_or_none()


async def get_by_id(db: AsyncSession, user_id: uuid.UUID) -> User | None:
    return await db.get(User, user_id)


async def create_user(
    db: AsyncSession,
    *,
    email: str,
    full_name: str,
    password: str,
    role: UserRole = UserRole.CONSUMER,
    commit: bool = True,
) -> User:
    user = User(
        email=email.lower(),
        full_name=full_name,
        hashed_password=hash_password(password),
        role=role,
    )
    db.add(user)
    if commit:
        await db.commit()
        await db.refresh(user)
    else:
        await db.flush()
    return user
