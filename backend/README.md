# EconoFácil — Backend API

Backend do ecossistema de compras inteligentes **EconoFácil**, construído em
**FastAPI + PostgreSQL** com arquitetura modular pronta para evoluir para
microserviços. Esta entrega cobre a **fundação** e o **módulo de autenticação
completo**, incluindo a camada de **Segurança e LGPD** prevista no Documento
Mestre.

---

## Stack

| Camada            | Tecnologia                                  |
|-------------------|---------------------------------------------|
| Framework         | FastAPI                                     |
| Banco de dados    | PostgreSQL (via `asyncpg`, SQLAlchemy 2.0)  |
| Migrações         | Alembic (assíncrono)                        |
| Senhas            | Argon2 (`argon2-cffi`)                       |
| Tokens            | JWT (access) + refresh token opaco revogável|
| 2FA               | TOTP (`pyotp`)                              |
| Otimização (Noor) | ILP via PuLP + CBC                          |
| Pagamentos        | PIX (BR Code EMV/BCB + CRC16) · `qrcode`    |
| Rate limiting     | slowapi                                     |
| Testes            | pytest + httpx + SQLite em memória          |

---

## Como rodar

### Opção A — Docker (recomendado)

```bash
cp .env.example .env          # ajuste SECRET_KEY antes de produção
docker compose up --build
```

API em `http://localhost:8000` · Docs interativas em `http://localhost:8000/docs`

### Opção B — Local

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env

# suba um PostgreSQL e ajuste DATABASE_URL no .env, depois:
uvicorn app.main:app --reload
```

> Em `ENVIRONMENT=development`, as tabelas são criadas automaticamente no start.
> Em produção, use Alembic (ver abaixo) e mantenha o auto-create desligado.

### Testes

```bash
pytest          # 10 testes de integração, roda sobre SQLite em memória
```

---

## Migrações (Alembic)

A URL do banco é lida automaticamente de `app.core.config`.

```bash
# gerar a primeira migração a partir dos modelos
alembic revision --autogenerate -m "estrutura inicial"

# aplicar
alembic upgrade head
```

---

## Estrutura

```
app/
├── core/        config, segurança (hash/JWT), banco, dependências, rate limit
├── models/      User, RefreshToken, AuditLog, Consent
├── schemas/     validação Pydantic (auth, user, token, lgpd)
├── services/    lógica de negócio (auth, user, audit, lgpd)
├── api/v1/      rotas: auth, users, lgpd
└── main.py      aplicação, middlewares, CORS, healthcheck
```

A separação **api → services → models** facilita extrair cada domínio
(auth, catálogo, carrinho, Noor...) para um serviço próprio no futuro, sem
reescrever a lógica.

---

## Endpoints

### Autenticação (`/api/v1/auth`)
| Método | Rota                        | Descrição                                   |
|--------|-----------------------------|---------------------------------------------|
| POST   | `/register`                 | Cria conta (consumidor/comerciante)         |
| POST   | `/login`                    | Login; exige `otp_code` se o 2FA estiver ativo |
| POST   | `/refresh`                  | Rotaciona o par de tokens                   |
| POST   | `/logout`                   | Revoga o refresh token                      |
| POST   | `/email/request-verification` | Solicita verificação de e-mail            |
| POST   | `/email/verify`             | Confirma e-mail via token                   |
| POST   | `/password/forgot`          | Solicita redefinição (resposta neutra)      |
| POST   | `/password/reset`           | Redefine via token e encerra sessões        |
| POST   | `/password/change`          | Troca de senha autenticada                  |
| POST   | `/2fa/setup`                | Gera segredo + URI do autenticador          |
| POST   | `/2fa/enable`               | Ativa o 2FA após validar o código           |
| POST   | `/2fa/disable`              | Desativa o 2FA                              |

### Usuário (`/api/v1/users`)
| Método | Rota   | Descrição                  |
|--------|--------|----------------------------|
| GET    | `/me`  | Perfil do usuário atual    |
| PATCH  | `/me`  | Atualiza dados do perfil   |

### LGPD (`/api/v1/lgpd`)
| Método | Rota         | Descrição                                          |
|--------|--------------|----------------------------------------------------|
| GET    | `/consents`  | Lista consentimentos                               |
| PUT    | `/consents`  | Atualiza consentimentos granulares                 |
| GET    | `/export`    | Exporta dados do titular (portabilidade, Art. 18)  |
| DELETE | `/account`   | Direito ao esquecimento (anonimização)             |

### Catálogo (`/api/v1/catalog`)
| Método | Rota                                  | Acesso      | Descrição                                              |
|--------|---------------------------------------|-------------|--------------------------------------------------------|
| GET    | `/categories`                         | público     | Lista categorias                                       |
| GET    | `/products`                           | público     | Busca/lista produtos com melhor preço unitário (RN-001)|
| GET    | `/products/{id}`                      | público     | Detalhe (PDP) com comparação entre lojas, ordenada     |
| POST   | `/categories`                         | comerciante | Cria categoria                                         |
| POST   | `/stores`                             | comerciante | Cria loja                                              |
| POST   | `/products`                           | comerciante | Adiciona produto ao catálogo universal                 |
| PUT    | `/stores/{store_id}/offers/{prod_id}` | comerciante | Cria/atualiza preço e estoque de um produto na loja    |

> **RN-001:** a comparação usa **preço unitário normalizado**. Cada produto guarda
> seu `base_size` (kg/l/un), então o preço por unidade é `preço / base_size` — um
> Leite 2L por R$ 8,00 (R$ 4,00/l) fica à frente de um 1L por R$ 4,29 (R$ 4,29/l),
> mesmo custando mais no total.

### Carrinho (`/api/v1/cart`) · consumidor autenticado
| Método | Rota                     | Descrição                                              |
|--------|--------------------------|--------------------------------------------------------|
| GET    | `/`                      | Carrinho ativo (cria se não houver), com validade      |
| POST   | `/items`                 | Adiciona item                                          |
| PATCH  | `/items/{product_id}`    | Altera quantidade (0 remove)                           |
| DELETE | `/items/{product_id}`    | Remove item                                            |
| DELETE | `/`                      | Esvazia o carrinho                                     |
| GET    | `/optimize`              | Compara loja única × split e recomenda (RN-018)        |
| POST   | `/checkout`              | Fecha o pedido (`strategy`: recommended/single/split)  |

### Pedidos (`/api/v1/orders`) · consumidor autenticado
| Método | Rota          | Descrição                          |
|--------|---------------|------------------------------------|
| GET    | `/`           | Histórico de pedidos               |
| GET    | `/{order_id}` | Detalhe do pedido (itens por loja) |

### Noor (`/api/v1/noor`)
| Método | Rota       | Descrição                                              |
|--------|------------|--------------------------------------------------------|
| GET    | `/status`  | Motor ativo, disponibilidade do solver e métricas      |

> **Noor Solver (motor de otimização).** A otimização de cestas resolve, de forma
> **exata**, qual loja atende cada item minimizando o custo total sob o teto de 3
> lojas (RN-018) — formulado como Programação Linear Inteira e resolvido com CBC
> (PuLP). É a evolução da heurística de enumeração: dá a mesma resposta ótima nos
> casos pequenos e **escala** onde a enumeração `C(n,3)` explodiria. A camada de
> otimização escolhe o motor automaticamente (`NOOR_SOLVER_ENABLED`) e cai na
> heurística se o solver não estiver disponível (`heuristic-fallback`). A decisão
> loja única × split e o limiar de 2% são compartilhados pelos dois motores.

### Portal do Comerciante (`/api/v1/merchant`) · comerciante (escopo de propriedade)
| Método | Rota                                   | Descrição                                          |
|--------|----------------------------------------|----------------------------------------------------|
| GET    | `/stores`                              | Minhas lojas                                       |
| GET    | `/stores/{id}/inventory`               | Catálogo/estoque/preços da loja                    |
| GET    | `/stores/{id}/promotions`             | Promoções (vencidas são encerradas na leitura)     |
| POST   | `/stores/{id}/promotions`             | Cria promoção (aplica o preço promocional)         |
| DELETE | `/promotions/{promo_id}`               | Encerra promoção (restaura o preço-base)           |
| GET    | `/orders`                              | Pedidos que incluem minhas lojas (itens da loja)   |
| PATCH  | `/orders/{order_id}/status`            | Atualiza o status de fulfillment                   |
| GET    | `/stores/{id}/report`                  | Relatório operacional (receita, unidades, top)     |

> **Escopo de propriedade.** Cada comerciante só acessa as lojas em que é dono
> (`Store.owner_id`); o admin acessa todas. A atualização de preço/estoque usa o
> endpoint de oferta do catálogo, agora com checagem de propriedade. As
> promoções rebaixam o preço vigente e guardam o anterior (exibido riscado no
> PDP), restaurado ao encerrar. **Simplificações do MVP:** o status do pedido é
> único para o pedido todo (fulfillment por loja fica para depois) e a expiração
> de promoções é aplicada na leitura (em produção, por agendador).

### Pagamentos (`/api/v1/payments`)
| Método | Rota              | Acesso     | Descrição                                  |
|--------|-------------------|------------|--------------------------------------------|
| GET    | `/{payment_id}`   | dono       | Consulta status do pagamento               |
| POST   | `/pix/webhook`    | PSP        | Confirma o pagamento Pix (segredo no header)|

O método de pagamento é escolhido no checkout (`payment_method`: `pix`,
`econopay` ou `card`).

> **PIX.** No checkout com Pix, o pedido entra como `awaiting_payment` e é gerado
> um **BR Code ("copia e cola") válido** seguindo o padrão EMV®/BCB — campos TLV,
> chave, valor e **CRC16-CCITT** — mais um QR em SVG. O provedor é plugável
> (`MockPixProvider` hoje; um PSP real implementa a mesma interface). A
> confirmação chega por **webhook** autenticado por segredo compartilhado
> (`PIX_WEBHOOK_SECRET`); ao confirmar, o pagamento vira `paid` e o pedido
> `placed`. **EconoPay** liquida na hora (stub de carteira); **cartão** ainda não
> está disponível. Nenhum dinheiro real é movimentado.

> **RN-018 (split):** o otimizador divide a compra em **até 3 lojas** e só
> recomenda o split quando a economia é de **pelo menos 2%** frente à melhor loja
> única — caso contrário prefere a conveniência de uma loja só. **RN-008:** o
> carrinho expira em 24h (logado). **RN-009:** itens sem estoque são sinalizados
> com sugestão de substitutos da mesma categoria. Esta é a heurística MVP que o
> **Noor Solver** assume e escala adiante.

---

## Decisões de segurança

- **Senhas**: hash Argon2; nunca armazenadas ou logadas em texto puro.
- **Access token** JWT de curta duração (stateless) + **refresh token** opaco
  armazenado apenas como hash SHA-256, com **rotação** a cada uso e revogação
  em troca/redefinição de senha.
- **Login** com verificação em tempo aproximadamente constante e mensagens de
  erro genéricas, para não revelar a existência de contas.
- **Rate limiting** no registro, login e recuperação de senha.
- **Auditoria**: toda ação sensível é registrada em `audit_logs`.
- **LGPD**: consentimento por finalidade, exportação e anonimização que
  preserva integridade referencial (não quebra históricos agregados).

---

## Próximos módulos sugeridos

As cinco Prioridades Técnicas do Documento Mestre estão concluídas sobre esta
fundação: ~~Backend FastAPI~~ ✅ · ~~Catálogo + comparação de preços~~ ✅ ·
~~Carrinho/Checkout/Pedidos (split RN-018)~~ ✅ · ~~Noor Solver — otimização
(ILP/CBC)~~ ✅ · ~~Portal do Comerciante~~ ✅ · ~~Integração PIX~~ ✅.

Evoluções previstas no roadmap do produto: liquidação Pix por loja no split,
fulfillment de pedido por loja, expiração agendada (carrinho/promoções/Pix),
e as capacidades V2/V3 da Noor (recomendações, previsão de consumo, detecção de
anomalias, qualidade de dados) com tracking de modelos via MLflow. No produto:
EconoClub, EconoPay/EconoCard e expansão para farmácias e pet shops.
