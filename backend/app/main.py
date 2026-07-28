"""Ponto de entrada da aplicação EconoFácil API."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.api.router import api_router
from app.core.config import settings
from app.core.rate_limit import limiter


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Em desenvolvimento, cria as tabelas automaticamente.
    # Em produção, use migrações Alembic (alembic upgrade head).
    if not settings.is_production:
        from app.core.database import engine
        from app.models import Base

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    if settings.SCHEDULER_ENABLED:
        from app.core import scheduler

        scheduler.start()

    yield

    if settings.SCHEDULER_ENABLED:
        from app.core import scheduler

        await scheduler.stop()


app = FastAPI(
    title=settings.PROJECT_NAME,
    version="0.1.0",
    description="Backend do ecossistema de compras inteligentes EconoFácil.",
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    docs_url="/docs",
    lifespan=lifespan,
)

# Rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.BACKEND_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.API_V1_STR)


@app.get("/health", tags=["infra"])
async def health_check():
    return {"status": "ok", "environment": settings.ENVIRONMENT}


# --------------------------------------------------------------------------- #
# Deploy combinado: a mesma imagem serve o site (build do Vite) e a API.
# Só ativa quando STATIC_DIR aponta para uma pasta com um index.html de
# verdade (ex.: /app/static no Dockerfile) — em dev, sem STATIC_DIR, o front
# roda separado via `npm run dev` e isto não é registrado.
# --------------------------------------------------------------------------- #
if settings.STATIC_DIR:
    _static_dir = Path(settings.STATIC_DIR)
    _index_html = _static_dir / "index.html"

    if _index_html.is_file():
        _assets_dir = _static_dir / "assets"
        if _assets_dir.is_dir():
            app.mount("/assets", StaticFiles(directory=_assets_dir), name="frontend-assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def serve_frontend(full_path: str):
            """Serve um arquivo estático se existir (ex.: favicon.ico), senão
            cai no index.html (fallback de rota do react-router). Como esta
            rota é registrada por último, as rotas de API/health/docs — já
            registradas acima — têm sempre precedência de correspondência."""
            candidate = _static_dir / full_path
            if full_path and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(_index_html)
