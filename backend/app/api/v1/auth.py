"""Endpoints de autenticação (/auth).

Obs.: este módulo NÃO usa ``from __future__ import annotations`` de propósito.
O decorator de rate limit (slowapi) envolve as funções, e anotações adiadas
(strings) impediriam o FastAPI de resolver os tipos do corpo da requisição.
"""
from typing import Annotated

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import ClientInfo, CurrentUser
from app.core.rate_limit import limiter
from app.core.security import (
    create_purpose_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.schemas.auth import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    MessageResponse,
    ResetPasswordRequest,
    TwoFactorSetupResponse,
    TwoFactorVerifyRequest,
    VerifyEmailRequest,
)
from app.schemas.token import LogoutRequest, RefreshRequest, TokenPair
from app.schemas.user import UserCreate, UserPublic
from app.services import auth_service, user_service
from app.services.audit_service import log_action

router = APIRouter(prefix="/auth", tags=["auth"])

DbSession = Annotated[AsyncSession, Depends(get_db)]


@router.post(
    "/register", response_model=UserPublic, status_code=status.HTTP_201_CREATED
)
@limiter.limit("10/hour")
async def register(
    request: Request, payload: UserCreate, db: DbSession, client: ClientInfo
):
    existing = await user_service.get_by_email(db, payload.email)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="E-mail já cadastrado",
        )
    user = await user_service.create_user(
        db,
        email=payload.email,
        full_name=payload.full_name,
        password=payload.password,
    )
    await log_action(db, action="user.register", user_id=user.id, **client)
    return user


@router.post("/login", response_model=TokenPair)
@limiter.limit("5/minute")
async def login(
    request: Request, payload: LoginRequest, db: DbSession, client: ClientInfo
):
    user = await user_service.get_by_email(db, payload.email)

    # verificação em tempo constante: sempre roda verify_password
    valid = (
        user is not None
        and user.is_active
        and verify_password(payload.password, user.hashed_password)
    )
    if not valid:
        await log_action(
            db,
            action="auth.login_failed",
            user_id=user.id if user else None,
            details={"email": payload.email},
            **client,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="E-mail ou senha inválidos",
        )

    # 2FA, se ativo
    if user.is_2fa_enabled:
        if not payload.otp_code or not auth_service.verify_totp(
            user.totp_secret, payload.otp_code
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Código de verificação (2FA) obrigatório ou inválido",
            )

    access, refresh = await auth_service.issue_tokens(db, user, **client)
    await log_action(db, action="auth.login", user_id=user.id, **client)
    return TokenPair(access_token=access, refresh_token=refresh)


@router.post("/refresh", response_model=TokenPair)
async def refresh(payload: RefreshRequest, db: DbSession):
    result = await auth_service.rotate_refresh_token(db, payload.refresh_token)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token inválido ou expirado",
        )
    access, new_refresh = result
    return TokenPair(access_token=access, refresh_token=new_refresh)


@router.post("/logout", response_model=MessageResponse)
async def logout(payload: LogoutRequest, db: DbSession):
    await auth_service.revoke_refresh_token(db, payload.refresh_token)
    return MessageResponse(message="Sessão encerrada")


# --------------------------------------------------------------------------- #
# Verificação de e-mail
# --------------------------------------------------------------------------- #
@router.post("/email/request-verification", response_model=MessageResponse)
async def request_email_verification(user: CurrentUser):
    token = create_purpose_token(str(user.id), purpose="verify_email")
    # Em produção: enfileirar envio de e-mail. Em dev, devolvemos o token.
    payload = {"message": "E-mail de verificação enviado"}
    if settings.DEBUG:
        payload["dev_token"] = token  # type: ignore[assignment]
    return MessageResponse(message=payload["message"])


@router.post("/email/verify", response_model=MessageResponse)
async def verify_email(payload: VerifyEmailRequest, db: DbSession):
    try:
        data = decode_token(payload.token)
        if data.get("purpose") != "verify_email":
            raise ValueError
    except (jwt.PyJWTError, ValueError):
        raise HTTPException(status_code=400, detail="Token inválido")

    user = await user_service.get_by_id(db, _uuid(data["sub"]))
    if user is None:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")
    user.is_verified = True
    await db.commit()
    await log_action(db, action="user.email_verified", user_id=user.id)
    return MessageResponse(message="E-mail verificado")


# --------------------------------------------------------------------------- #
# Redefinição de senha
# --------------------------------------------------------------------------- #
@router.post("/password/forgot", response_model=MessageResponse)
@limiter.limit("5/hour")
async def forgot_password(
    request: Request, payload: ForgotPasswordRequest, db: DbSession
):
    user = await user_service.get_by_email(db, payload.email)
    if user is not None:
        token = create_purpose_token(str(user.id), purpose="reset_password")
        # Em produção: enviar e-mail com o link contendo o token.
        await log_action(db, action="auth.password_reset_requested", user_id=user.id)
    # resposta idêntica para não revelar se o e-mail existe
    return MessageResponse(
        message="Se o e-mail existir, enviaremos instruções de redefinição"
    )


@router.post("/password/reset", response_model=MessageResponse)
async def reset_password(payload: ResetPasswordRequest, db: DbSession):
    try:
        data = decode_token(payload.token)
        if data.get("purpose") != "reset_password":
            raise ValueError
    except (jwt.PyJWTError, ValueError):
        raise HTTPException(status_code=400, detail="Token inválido ou expirado")

    user = await user_service.get_by_id(db, _uuid(data["sub"]))
    if user is None:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")

    user.hashed_password = hash_password(payload.new_password)
    await auth_service.revoke_all_user_tokens(db, user.id)  # encerra sessões
    await db.commit()
    await log_action(db, action="auth.password_reset", user_id=user.id)
    return MessageResponse(message="Senha redefinida com sucesso")


@router.post("/password/change", response_model=MessageResponse)
async def change_password(
    payload: ChangePasswordRequest, db: DbSession, user: CurrentUser
):
    if not verify_password(payload.current_password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Senha atual incorreta")
    user.hashed_password = hash_password(payload.new_password)
    await auth_service.revoke_all_user_tokens(db, user.id)
    await db.commit()
    await log_action(db, action="auth.password_changed", user_id=user.id)
    return MessageResponse(message="Senha alterada")


# --------------------------------------------------------------------------- #
# 2FA (TOTP)
# --------------------------------------------------------------------------- #
@router.post("/2fa/setup", response_model=TwoFactorSetupResponse)
async def setup_2fa(db: DbSession, user: CurrentUser):
    if user.is_2fa_enabled:
        raise HTTPException(status_code=400, detail="2FA já está ativo")
    secret = auth_service.generate_totp_secret()
    user.totp_secret = secret  # ativado apenas após confirmação
    await db.commit()
    return TwoFactorSetupResponse(
        secret=secret,
        otpauth_uri=auth_service.build_otpauth_uri(secret, user.email),
    )


@router.post("/2fa/enable", response_model=MessageResponse)
async def enable_2fa(
    payload: TwoFactorVerifyRequest, db: DbSession, user: CurrentUser
):
    if not user.totp_secret:
        raise HTTPException(status_code=400, detail="Inicie o setup do 2FA primeiro")
    if not auth_service.verify_totp(user.totp_secret, payload.otp_code):
        raise HTTPException(status_code=400, detail="Código inválido")
    user.is_2fa_enabled = True
    await db.commit()
    await log_action(db, action="auth.2fa_enabled", user_id=user.id)
    return MessageResponse(message="2FA ativado")


@router.post("/2fa/disable", response_model=MessageResponse)
async def disable_2fa(
    payload: TwoFactorVerifyRequest, db: DbSession, user: CurrentUser
):
    if not user.is_2fa_enabled or not user.totp_secret:
        raise HTTPException(status_code=400, detail="2FA não está ativo")
    if not auth_service.verify_totp(user.totp_secret, payload.otp_code):
        raise HTTPException(status_code=400, detail="Código inválido")
    user.is_2fa_enabled = False
    user.totp_secret = None
    await db.commit()
    await log_action(db, action="auth.2fa_disabled", user_id=user.id)
    return MessageResponse(message="2FA desativado")


def _uuid(value: str):
    import uuid as _u

    return _u.UUID(value)
