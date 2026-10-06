# Conjo Chat — avisos de projeto no Matrix

Cada projeto do Conjo Tasks pode ter uma sala no Conjo Chat
(https://chat.conjosa.com.br) onde um bot publica avisos das tarefas: criação,
mudança de estado, atribuição e novos comentários. A sala também traz o board
do projeto como widget do Element.

## Variáveis de ambiente (serviços `api` e `worker`)

| Variável                    | Exemplo                        | Uso                                                                   |
| --------------------------- | ------------------------------ | --------------------------------------------------------------------- |
| `CONJO_CHAT_HOMESERVER_URL` | `https://chat.conjosa.com.br`  | Base da API Matrix (Client-Server).                                   |
| `CONJO_CHAT_WEB_URL`        | `https://chat.conjosa.com.br`  | Links para as salas (`<web>/#/room/<room_id>`). Padrão: o homeserver. |
| `CONJO_CHAT_BOT_USER`       | `tasks`                        | Localpart do bot (padrão `tasks`).                                    |
| `CONJO_CHAT_BOT_PASSWORD`   | (segredo)                      | Senha do bot, a mesma de `CONJO_TASKS_BOT_PASSWORD` no Synapse.       |
| `CONJO_CHAT_SERVER_NAME`    | `chat.conjosa.com.br`          | `server_name` do Synapse (padrão `chat.conjosa.com.br`).              |
| `TASKS_PUBLIC_URL`          | `https://tasks.conjosa.com.br` | Base dos links para tarefas e board. Padrão: `WEB_URL`.               |

Sem `CONJO_CHAT_HOMESERVER_URL` ou `CONJO_CHAT_BOT_PASSWORD` a integração fica
desligada e a tela do projeto mostra "Chat não configurado neste servidor".

## Como funciona

1. Em **Configurações do projeto → Chat**, um admin clica em criar sala. A API
   (`POST /api/workspaces/<slug>/projects/<id>/chat-integration/create-room/`)
   faz login como `@tasks:<server_name>` e cria a sala `Tasks · <IDENT>` com
   alias `#tasks-<ident>` (sem alias se ele já existir), sem criptografia, sem
   federação, pública no diretório interno e só o bot/moderadores podem postar.
   A sala recebe o estado `br.com.conjosa.tasks.project` e o widget
   `conjo_tasks_board` apontando para o board. Repetir a ação numa sala já
   criada apenas reaplica nome, tópico, estado e widget.
2. O pipeline de atividades (`issue_activity`) chama
   `enqueue_chat_notifications`, que só enfileira a task Celery
   `notify_chat_room` se o projeto tiver a integração ativa e uma sala.
3. A task monta a mensagem em pt-BR (HTML + texto puro), respeita os
   `notify_*` do projeto e envia com um `txn_id` fixo por aviso, então
   reenvios do Celery não duplicam mensagens.
4. O token do bot fica no cache do Django (`conjo_chat:bot_token`). Em 401 o
   cliente faz login de novo uma vez; em 429 ou erro 5xx a task é reagendada
   (até 5 vezes) respeitando `retry_after_ms`.

Outros endpoints: `GET`/`PATCH .../chat-integration/` (membros leem, admins
alteram `enabled` e `notify_*`) e `POST .../chat-integration/test/` (mensagem de
teste).

## Embutir o board no chat

O nginx do app web (`apps/web/nginx/nginx.conf`) não envia mais
`X-Frame-Options: DENY`; no lugar envia
`Content-Security-Policy: frame-ancestors 'self' https://chat.conjosa.com.br`.
Como tasks e chat estão no mesmo site (`conjosa.com.br`), o cookie de sessão
do Plane funciona dentro do iframe. Se o domínio do chat mudar, ajuste o
cabeçalho.

## Limitações

- Tarefas criadas ou alteradas pelo MCP (`/mcp`) não geram avisos, porque não
  passam pelo pipeline `issue_activity`.
- Responsáveis definidos no momento da criação não geram aviso de atribuição;
  só o aviso "criou".
- Comentários editados ou apagados, prioridade, datas e etiquetas não geram
  avisos.
- A sala não convida os membros do projeto: quem quiser acompanhar entra pelo
  diretório de salas ou pelo link exibido na configuração.
- Se o bot for removido da sala ou a sala for apagada no chat, os envios
  falham (registrados no log) até um admin clicar em criar sala de novo, o que
  cria uma sala nova quando o bot não tem mais acesso à antiga.
