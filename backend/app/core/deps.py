"""Dependências do FastAPI: usuário atual, controle de papel e contexto."""
from __future__ import annotations

import uuid
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.security import decode_token
from app.models.user import User, UserRole

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_STR}/auth/login", auto_error=True
)

_CREDENTIALS_ERROR = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Credenciais inválidas",
    headers={"WWW-Authenticate": "Bearer"},
)


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            raise _CREDENTIALS_ERROR
        user_id = payload.get("sub")
        if user_id is None:
            raise _CREDENTIALS_ERROR
    except jwt.PyJWTError:
        raise _CREDENTIALS_ERROR

    user = await db.get(User, uuid.UUID(user_id))
    if user is None or not user.is_active:
        raise _CREDENTIALS_ERROR
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_role(*roles: UserRole):
    async def _checker(user: CurrentUser) -> User:
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Permissão insuficiente",
            )
        return user

    return _checker


def get_client_info(request: Request) -> dict[str, str | None]:
    client = request.client.host if request.client else None
    forwarded = request.headers.get("x-forwarded-for")
    ip = forwarded.split(",")[0].strip() if forwarded else client
    return {"ip_address": ip, "user_agent": request.headers.get("user-agent")}


ClientInfo = Annotated[dict, Depends(get_client_info)]
