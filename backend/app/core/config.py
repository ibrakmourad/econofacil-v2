"""Configuração central da aplicação, carregada de variáveis de ambiente."""
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Aplicação
    PROJECT_NAME: str = "EconoFácil API"
    ENVIRONMENT: str = "development"
    API_V1_STR: str = "/api/v1"
    DEBUG: bool = True

    # Segurança
    SECRET_KEY: str = "dev-secret-change-me"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    EMAIL_TOKEN_EXPIRE_MINUTES: int = 60

    # CORS
    BACKEND_CORS_ORIGINS: list[str] = ["http://localhost:5173"]

    # Banco de dados
    DATABASE_URL: str = "postgresql+asyncpg://econofacil:econofacil@localhost:5432/econofacil"

    # 2FA
    TOTP_ISSUER: str = "EconoFácil"

    # Noor (otimização de cestas)
    NOOR_SOLVER_ENABLED: bool = True
    NOOR_FORCE_HEURISTIC: bool = False

    # Pagamentos (PIX)
    PIX_KEY: str = "pagamentos@econofacil.com.br"
    PIX_CHARGE_TTL_SECONDS: int = 3600
    PIX_WEBHOOK_SECRET: str = "dev-pix-webhook-secret"

    # LGPD
    TERMS_VERSION: str = "2025.1"

    # Agendador de expirações (RN-021) — carrinho, promoções e cobranças Pix
    # antes eram expirados só oportunisticamente na leitura; agora também
    # rodam em um laço de background dentro do próprio processo da API.
    SCHEDULER_ENABLED: bool = True
    SCHEDULER_INTERVAL_SECONDS: int = 60

    # Deploy combinado (backend serve o front) — ver app/main.py.
    # Quando configurado (aponta para a pasta com o build do Vite, ex.:
    # /app/static no Dockerfile), a própria API serve o site e faz fallback
    # de rotas SPA para index.html. Vazio = a API roda sozinha (dev, onde o
    # front sobe separado via `npm run dev`).
    STATIC_DIR: str = ""

    @field_validator("BACKEND_CORS_ORIGINS", mode="before")
    @classmethod
    def _split_cors(cls, v):
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
