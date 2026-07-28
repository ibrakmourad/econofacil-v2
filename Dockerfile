# ===========================================================================
# EconoFácil — imagem única (site React + API FastAPI no mesmo serviço)
# Etapa 1: monta o front-end.  Etapa 2: roda a API servindo o site pronto.
# ===========================================================================

# --- Etapa 1: build do front-end ---
FROM node:20-slim AS frontend
WORKDIR /fe
COPY frontend/package*.json ./
RUN npm ci || npm install
COPY frontend/ ./
# o site chama a API na mesma origem
ENV VITE_API_URL=/api/v1
RUN npm run build         # gera /fe/dist

# --- Etapa 2: backend + site ---
FROM python:3.12-slim
WORKDIR /app

COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./
COPY --from=frontend /fe/dist ./static

ENV STATIC_DIR=/app/static \
    ENVIRONMENT=production \
    DEBUG=false \
    DATABASE_URL=sqlite+aiosqlite:///./econofacil.db

# popula os dados de demonstração (idempotente) e sobe a API na porta do Render
CMD ["sh", "-c", "python seed.py; uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
