"""Funções de segurança: hash de senha, JWT e tokens de atualização.

Design adotado:
- Senha: hash com Argon2 (recomendação atual da OWASP).
- Access token: JWT assinado (stateless, curta duração).
- Refresh token: opaco e aleatório, armazenado apenas como hash SHA-256
  no banco — assim pode ser revogado e nunca é guardado em texto puro.
- Tokens de e-mail / reset de senha: JWT de curta duração com 'purpose'.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error

from app.core.config import settings

_ph = PasswordHasher()


# --------------------------------------------------------------------------- #
# Senhas
# --------------------------------------------------------------------------- #
def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return _ph.verify(hashed_password, plain_password)
    except Argon2Error:
        return False


def needs_rehash(hashed_password: str) -> bool:
    """Indica se o hash deve ser regenerado (parâmetros do Argon2 mudaram)."""
    try:
        return _ph.check_needs_rehash(hashed_password)
    except Argon2Error:
        return False


# --------------------------------------------------------------------------- #
# JWT (access e tokens de propósito específico)
# --------------------------------------------------------------------------- #
def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_access_token(subject: str, role: str) -> str:
    now = _now()
    payload = {
        "sub": str(subject),
        "role": role,
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_purpose_token(subject: str, purpose: str) -> str:
    """Token curto para verificação de e-mail ou redefinição de senha."""
    now = _now()
    payload = {
        "sub": str(subject),
        "purpose": purpose,
        "type": "purpose",
        "iat": now,
        "exp": now + timedelta(minutes=settings.EMAIL_TOKEN_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_token(token: str) -> dict:
    """Decodifica e valida assinatura/expiração. Lança jwt.PyJWTError em erro."""
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])


# --------------------------------------------------------------------------- #
# Refresh tokens (opacos, armazenados como hash)
# --------------------------------------------------------------------------- #
def generate_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
