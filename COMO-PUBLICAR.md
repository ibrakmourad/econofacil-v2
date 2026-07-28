# Como publicar o EconoFácil (demonstração)

Este guia coloca o EconoFácil no ar com um **link público** que qualquer pessoa
abre no navegador ou no celular — sem instalar nada. É **tudo pelo navegador**,
não precisa de terminal nem de conhecimento técnico. Leva uns **15 minutos**, e
o plano usado é **gratuito**.

Você vai fazer duas coisas:
1. Colocar o código no **GitHub**.
2. Mandar o **Render** publicar a partir do GitHub.

---

## Antes de começar

- Descompacte o arquivo `econofacil-deploy.zip`. Vai aparecer uma pasta chamada
  `econofacil-deploy` com, lá dentro: `backend`, `frontend`, `Dockerfile`,
  `render.yaml` e este guia.
- Tenha sua conta do **GitHub** à mão.

---

## Parte 1 — Colocar o código no GitHub

1. Acesse **github.com** e entre na sua conta.
2. No canto superior direito, clique no **+** e em **New repository**.
3. Em *Repository name*, escreva `econofacil`. Deixe como **Public**. Clique em
   **Create repository**.
4. Na página que abrir, clique no link **“uploading an existing file”**
   (fica no meio da tela, na frase "…or upload an existing file").
5. Abra a pasta `econofacil-deploy` no seu computador. **Selecione tudo que está
   DENTRO dela** (as pastas `backend` e `frontend`, o `Dockerfile`, o
   `render.yaml`, etc.) e **arraste** para a área de upload do GitHub.
   > ⚠️ Importante: arraste o **conteúdo** da pasta, não a pasta inteira. No
   > final, o `Dockerfile` e o `render.yaml` precisam ficar na **raiz** do
   > repositório (a primeira página do projeto), e não dentro de outra pasta.
6. Espere os arquivos subirem e clique no botão verde **Commit changes**.

Pronto — seu código está no GitHub.

---

## Parte 2 — Publicar no Render

1. Acesse **render.com** e clique em **Get Started** / **Sign up**.
2. Escolha **entrar com o GitHub** e autorize o Render a ver seus repositórios.
3. No painel do Render, clique em **New +** (canto superior) e escolha
   **Blueprint**.
4. Selecione o repositório **econofacil** que você acabou de criar.
5. O Render vai ler o arquivo `render.yaml` sozinho e mostrar um serviço chamado
   **econofacil-demo** no plano **Free**. Clique em **Apply** (ou **Create**).
6. Agora é só esperar. O Render vai montar o app — leva de **5 a 10 minutos** na
   primeira vez (você vê um log rolando; é normal). Quando aparecer **“Live”**
   em verde, está no ar.

---

## Parte 3 — Pegar o link e compartilhar

No topo da página do serviço no Render aparece o endereço, algo como:

```
https://econofacil-demo.onrender.com
```

Esse é **o link**. Abra para testar e **mande para a pessoa**. Ela só precisa
abrir no navegador ou no celular — não instala nada.

No app: toque em **Criar conta**, navegue pelo catálogo, adicione itens ao
carrinho, veja o **split sugerido** e finalize no **PIX**.

---

## O que avisar para a pessoa (importante e honesto)

- **A primeira abertura pode demorar ~1 minuto.** No plano gratuito o serviço
  “dorme” quando ninguém usa por 15 minutos; no próximo acesso ele “acorda” e
  carrega devagar só na primeira tela. Depois fica rápido.
- **É uma demonstração.** Os dados de teste (contas e pedidos criados) podem ser
  apagados quando o serviço reinicia. O catálogo de produtos se recria sozinho,
  então a loja sempre aparece cheia. Para uso de verdade (dados que ficam
  guardados e sem “dormir”), é preciso um plano pago — me avise que eu preparo.

---

## Dá para entrar como administrador?

O sistema já vem com um usuário administrador para você espiar:

- **E-mail:** `admin@econofacil.com`
- **Senha:** `admin12345`

Clientes normais criam a própria conta pela tela de cadastro.

---

## (Opcional) Confirmar um pagamento PIX

Na tela do pedido aparece o **código PIX e o QR Code de verdade**. Como nenhum
dinheiro real é movimentado, a confirmação não acontece sozinha. Para mostrar o
pedido virando “Confirmado” numa demonstração, dá para simular a confirmação —
mas isso já é um passo técnico (precisa de um comando e de um segredo que fica
nas configurações do serviço no Render). Para a maioria das demonstrações, basta
mostrar a tela com o código PIX gerado. Se quiser fazer essa parte, me chame que
eu te passo o passo a passo.
