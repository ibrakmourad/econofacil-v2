# EconoFácil — Front-end

App **React (Vite)** com as **13 telas** do EconoFácil, funcional e integrado à
API do backend FastAPI. Mobile-first, na identidade visual da marca.

## Rodando

Pré-requisito: o **backend** rodando (ver o projeto `econofacil-backend`) e
populado com o `seed.py`.

```bash
cp .env.example .env          # ajuste VITE_API_URL se necessário
npm install
npm run dev                   # abre em http://localhost:5173
```

O backend já libera `http://localhost:5173` no CORS. Por padrão o app aponta
para `http://localhost:8000/api/v1` (configurável em `VITE_API_URL`).

### Passo a passo do zero

```bash
# 1) Backend
cd econofacil-backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python seed.py                # popula catálogo + admin
uvicorn app.main:app --reload

# 2) Front-end (em outro terminal)
cd econofacil-frontend
npm install && npm run dev
```

Depois, no app: **Criar conta** (consumidor) → navegar no catálogo → adicionar
ao carrinho → ver o split sugerido → checkout no PIX.

> **Confirmar o PIX:** o pagamento é confirmado por webhook do PSP. Em
> desenvolvimento, simule com o `txid` mostrado no pedido:
>
> ```bash
> curl -X POST http://localhost:8000/api/v1/payments/pix/webhook \
>   -H "Content-Type: application/json" \
>   -H "X-Webhook-Token: dev-pix-webhook-secret" \
>   -d '{"txid":"SEU_TXID"}'
> ```
> Toque em **Atualizar status** na tela do pedido para ver virar "Confirmado".

## As 13 telas e o que cada uma consome

| Tela | Rota | Backend |
|------|------|---------|
| Home | `/` | `GET /catalog/products`, `/catalog/categories` |
| Login | `/login` | `POST /auth/login` (com 2FA opcional) |
| Cadastro | `/cadastro` | `POST /auth/register` |
| Recuperação de Senha | `/recuperar-senha` | `POST /auth/password/forgot` |
| Categoria | `/categoria/:id` | `GET /catalog/products?category_id=` |
| Produto (PDP) | `/produto/:id` | `GET /catalog/products/:id` (comparação) |
| Carrinho | `/carrinho` | `/cart`, `/cart/optimize` (split RN-018) |
| Checkout | `/checkout` | `POST /cart/checkout` (estratégia + pagamento) |
| Pedido Confirmado | `/pedido/:id` | `GET /orders/:id` (PIX copia-e-cola + QR) |
| Pedidos | `/pedidos` | `GET /orders` |
| Perfil | `/perfil` | `GET /users/me`, `/lgpd/*` (consent, export, exclusão) |
| Receitas | `/receitas` | curadas no app; usam `GET /catalog/products` |
| Listas | `/listas` | `localStorage` (módulo de Listas ainda não no backend) |

## Arquitetura

- `src/api/client.js` — cliente HTTP com tokens (access + refresh) e renovação
  automática no 401.
- `src/context/` — `AuthContext` (sessão) e `CartContext` (carrinho + badge).
- `src/pages/` — uma tela por arquivo. `src/components/ui.jsx` — peças comuns.
- `src/styles.css` — design system (verde/azul, mobile-first, abas inferiores).

Receitas e Listas são honestamente mais simples porque os módulos
correspondentes ainda não existem no backend — entram numa fase futura.
