# Integração com o GitHub (estilo Jira)

O Tasks vincula branches, commits e pull requests às tarefas pela **chave** da tarefa (`MAN-12`):

| Onde               | Exemplo                                     | Regra                    |
| ------------------ | ------------------------------------------- | ------------------------ |
| Nome da branch     | `man-12-corrigir-login`                     | maiúsculas ou minúsculas |
| Mensagem do commit | `MAN-12: corrige login`, `fix(MAN-12): ...` | chave em MAIÚSCULAS      |
| Pull request       | título, corpo ou branch de origem           | idem                     |

Os itens aparecem na tarefa, na seção **Desenvolvimento** (com o botão "Criar branch", que copia o nome sugerido
ou `git checkout -b ...`).

## Smart commits

Comandos depois da chave, na mesma linha da mensagem do commit:

- `MAN-12 #comment texto` adiciona um comentário na tarefa;
- `MAN-12 #done` (ou `#concluido`, `#em-revisao`, `#em-andamento`, ou o nome de qualquer estado) move a tarefa.

Só valem se o e-mail do autor do commit for o de um membro do workspace, e rodam uma vez por commit.
Podem ser desligados por projeto.

## Automações de pull request (por projeto)

Em Configurações do projeto → GitHub: estado para quando um PR que cita a tarefa é **aberto** (rascunhos não
contam) e quando é **mergeado**. Se o autor do PR não tiver conta no Tasks, quem aparece na atividade é o bot
"GitHub". Se o projeto tiver sala no Conjo Chat, a sala recebe "fulano abriu/mergeou o PR #7" (pode ser
desligado em Configurações → Conjo Chat).

## Configuração do servidor

- Variável `CONJO_GITHUB_WEBHOOK_SECRET` (serviços `api` e `worker`); sem ela o webhook responde 404.
- Opcional: `CONJO_GITHUB_WORKSPACE_SLUG` (padrão `conjosa`).
- Webhook na organização do GitHub (Settings → Webhooks): URL `https://tasks.conjosa.com.br/api/conjo/github/webhook/`,
  content type `application/json`, o mesmo secret, eventos **Pushes**, **Branch or tag creation**,
  **Branch or tag deletion** e **Pull requests**.
