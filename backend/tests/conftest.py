"""Fixtures de teste: banco SQLite em memória e cliente HTTP assíncrono."""
import os

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("DEBUG", "false")
# o ASGITransport do httpx não dispara eventos de lifespan, então o laço de
# background nunca inicia nos testes de qualquer forma — mas desativamos
# explicitamente por precaução (ex.: se o transporte de teste mudar).
os.environ.setdefault("SCHEDULER_ENABLED", "false")

import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.core.database import get_db  # noqa: E402
from app.core.rate_limit import limiter  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base  # noqa: E402

# desliga o rate limit durante os testes
limiter.enabled = False

test_engine = create_async_engine(
    "sqlite+aiosqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = async_sessionmaker(test_engine, expire_on_commit=False)


async def _override_get_db():
    async with TestSession() as session:
        yield session


app.dependency_overrides[get_db] = _override_get_db


@pytest_asyncio.fixture(autouse=True)
async def _setup_db():
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
def make_privileged_user():
    """Cria usuários com papel elevado direto no banco (fora do cadastro público)."""
    from app.models.user import UserRole
    from app.services import user_service

    async def _make(email: str, password: str, role: UserRole):
        async with TestSession() as session:
            await user_service.create_user(
                session,
                email=email,
                full_name="Privileged",
                password=password,
                role=role,
            )

    return _make


@pytest_asyncio.fixture
async def db():
    async with TestSession() as session:
        yield session
