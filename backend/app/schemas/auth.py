"""Schemas dos fluxos de autenticação."""
from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    otp_code: str | None = Field(
        default=None, description="Código TOTP, se o 2FA estiver ativo"
    )


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(min_length=8, max_length=128)


class VerifyEmailRequest(BaseModel):
    token: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)


# --- 2FA ---
class TwoFactorSetupResponse(BaseModel):
    secret: str
    otpauth_uri: str


class TwoFactorVerifyRequest(BaseModel):
    otp_code: str = Field(min_length=6, max_length=6)


class MessageResponse(BaseModel):
    message: str
