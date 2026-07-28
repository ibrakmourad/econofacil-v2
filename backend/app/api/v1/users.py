"""Endpoints de perfil de usuário (/users)."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import CurrentUser
from app.schemas.user import UserPublic, UserUpdate
from app.services.audit_service import log_action

router = APIRouter(prefix="/users", tags=["users"])

DbSession = Annotated[AsyncSession, Depends(get_db)]


@router.get("/me", response_model=UserPublic)
async def read_me(user: CurrentUser):
    return user


@router.patch("/me", response_model=UserPublic)
async def update_me(payload: UserUpdate, db: DbSession, user: CurrentUser):
    if payload.full_name is not None:
        user.full_name = payload.full_name
    await db.commit()
    await db.refresh(user)
    await log_action(db, action="user.profile_updated", user_id=user.id)
    return user
