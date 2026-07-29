# Deploy do Plane (Community) no CapRover

Esta pasta prepara o Plane para rodar como **um único app CapRover** usando a
imagem **All-In-One (AIO)** — web, admin, space, API, worker, beat, live server e
proxy Caddy, todos no mesmo container, gerenciados pelo Supervisor.

> **Importante:** a imagem *monta* as imagens oficiais pré-construídas
> (`makeplane/plane-*:v0.27.1`). Ela **não compila** o código da sua working tree.
> Para publicar alterações locais, você precisaria buildar e publicar cada imagem
> de serviço antes.

---

## Serviços externos obrigatórios

O container do Plane **não** sobe banco, cache, fila nem storage. Você precisa
provisionar (podem ser outros apps no próprio CapRover, ou serviços gerenciados):

| Serviço          | Para quê                          | Exemplo de app CapRover        |
| ---------------- | --------------------------------- | ------------------------------ |
| **PostgreSQL**   | Banco de dados principal          | One-Click App: PostgreSQL      |
| **Redis**        | Cache / sessões                   | One-Click App: Redis           |
| **RabbitMQ**     | Fila de tarefas (worker/beat)     | One-Click App: RabbitMQ        |
| **S3 / MinIO**   | Upload de arquivos e anexos       | One-Click App: MinIO           |

---

## Passo a passo

1. **Crie o app** no painel do CapRover (ex.: `plane`). Ative **HTTPS** e o
   **Force HTTPS** depois que estiver no ar.

2. **Deploy da imagem** — a partir da raiz do repositório (onde está o
   `captain-definition`):

   ```bash
   caprover deploy
   ```

   Selecione o app `plane`. O CapRover vai buildar usando
   `deployments/caprover/Dockerfile`.

3. **Container HTTP Port**: em *App Configs*, deixe **80** (padrão). O Caddy
   interno escuta em `:80` e o CapRover faz a terminação TLS.

4. **Variáveis de ambiente**: cole o bloco do arquivo
   [`env.caprover.example`](./env.caprover.example) em
   *App Configs → Environmental Variables* (Bulk Edit) e ajuste os valores.

5. **Persistência (opcional, recomendado):** em *App Configs → Persistent
   Directories*, mapeie `/app/data` e `/app/logs` para volumes nomeados, caso
   queira manter logs entre deploys.

6. Salve e reinicie. Acompanhe *App Logs* — o Supervisor sobe o migrator
   primeiro (roda as migrations do Django) e depois os demais serviços.

---

## Variáveis de ambiente

### Obrigatórias

| Variável                | Descrição                                                                 |
| ----------------------- | ------------------------------------------------------------------------- |
| `DOMAIN_NAME`           | Domínio (ou IP) do app, **sem** protocolo. Ex.: `plane.seudominio.com`    |
| `DATABASE_URL`          | Conexão PostgreSQL: `postgresql://user:senha@host:5432/plane`             |
| `REDIS_URL`             | Conexão Redis: `redis://host:6379/`                                        |
| `AMQP_URL`              | Conexão RabbitMQ: `amqp://user:senha@host:5672/vhost`                      |
| `AWS_REGION`            | Região do S3. Ex.: `us-east-1` (para MinIO, qualquer valor, ex. `us-east-1`) |
| `AWS_ACCESS_KEY_ID`     | Access key do S3/MinIO                                                     |
| `AWS_SECRET_ACCESS_KEY` | Secret key do S3/MinIO                                                     |
| `AWS_S3_BUCKET_NAME`    | Nome do bucket de uploads                                                  |

> Se algum desses estiver faltando, o container encerra na inicialização com a
> lista do que faltou (ver `start.sh`).

### Fortemente recomendadas em produção

| Variável                 | Descrição                                                                                          |
| ------------------------ | -------------------------------------------------------------------------------------------------- |
| `SECRET_KEY`             | Chave secreta do Django. **Defina explicitamente** — o container é efêmero e a geração automática se perde a cada redeploy, invalidando sessões. Gere com `openssl rand -hex 32`. |
| `LIVE_SERVER_SECRET_KEY` | Segredo do live server (colaboração em tempo real). Gere com `openssl rand -hex 32`.               |
| `APP_PROTOCOL`           | `https` (o CapRover serve via HTTPS). Define `WEB_URL`/CORS corretamente. Padrão: `http`.          |

### Opcionais

| Variável              | Padrão                             | Descrição                                                        |
| --------------------- | ---------------------------------- | ---------------------------------------------------------------- |
| `AWS_S3_ENDPOINT_URL` | `https://s3.<region>.amazonaws.com`| Endpoint do S3. Para MinIO aponte para a URL do MinIO.           |
| `SITE_ADDRESS`        | `:80`                              | Bind interno do Caddy. **Não altere** no CapRover.               |
| `FILE_SIZE_LIMIT`     | `5242880` (5 MB)                   | Limite de upload em bytes.                                       |
| `GUNICORN_WORKERS`    | `1`                                | Workers do Gunicorn (API).                                       |
| `API_KEY_RATE_LIMIT`  | `60/minute`                        | Rate limit por API key.                                          |
| `AUTHENTICATION_RATE_LIMIT` | `10/minute`                  | Rate limit dos endpoints de autenticação anônima.               |
| `USE_MINIO`           | `0`                                | Deixe `0` — o MinIO embutido do AIO não é usado neste setup.     |
| `WEBHOOK_ALLOWED_IPS` | (vazio)                            | IPs/CIDRs permitidos como destino de webhook.                    |
| `WEBHOOK_ALLOWED_HOSTS`| (vazio)                           | Hostnames que ignoram a checagem SSRF de webhook.                |

---

## Notas

- **TLS:** deixe o CapRover cuidar dos certificados (Let's Encrypt). O Caddy
  interno fica em HTTP na `:80`; **não** configure `CERT_EMAIL`/`SITE_ADDRESS`
  para HTTPS aqui, senão você teria duas camadas tentando emitir certificado.
- **Migrations:** rodam automaticamente no boot (serviço `migrator` no
  `supervisor.conf`), antes de API/worker.
- **Admin (God Mode):** acessível em `https://<DOMAIN_NAME>/god-mode`.
- **Versão:** para fixar outra versão do Plane, passe o build-arg
  `PLANE_VERSION` (ex.: editando o `captain-definition` para incluir
  `dockerfilePath` + variáveis, ou alterando o `ARG PLANE_VERSION` no Dockerfile).
