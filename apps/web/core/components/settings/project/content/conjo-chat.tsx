/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { ExternalLink, Info, RefreshCw, Send } from "lucide-react";
import { observer } from "mobx-react";
import { useState } from "react";
import useSWR from "swr";
// plane imports
import { Button } from "@plane/propel/button";
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import { ProjectChatIntegrationService } from "@plane/services";
import type {
  TProjectChatIntegration,
  TProjectChatIntegrationNotifyKey,
  TProjectChatIntegrationUpdate,
} from "@plane/types";
import { Loader, ToggleSwitch } from "@plane/ui";
// components
import { SettingsBoxedControlItem } from "@/components/settings/boxed-control-item";

const chatIntegrationService = new ProjectChatIntegrationService();

type Props = {
  projectId: string;
  workspaceSlug: string;
};

const NOTIFY_OPTIONS: { key: TProjectChatIntegrationNotifyKey; title: string; description: string }[] = [
  {
    key: "notify_issue_created",
    title: "Tarefa criada",
    description: "Avisa quando uma nova tarefa é criada no projeto.",
  },
  {
    key: "notify_state_changed",
    title: "Mudança de estado",
    description: "Avisa quando uma tarefa muda de estado no board.",
  },
  {
    key: "notify_assignee_changed",
    title: "Atribuição",
    description: "Avisa quando alguém é atribuído ou removido de uma tarefa.",
  },
  {
    key: "notify_comment_created",
    title: "Comentários",
    description: "Avisa quando uma tarefa recebe um novo comentário.",
  },
  {
    key: "notify_github",
    title: "Pull requests do GitHub",
    description: "Avisa quando um pull request que cita uma tarefa do projeto é aberto ou mergeado.",
  },
];

const HELP_TEXT =
  "Na sala do chat você também pode usar /tarefa e ver o board do projeto no painel lateral. Cada pessoa conecta a própria conta do Tasks em Configurações → Integrações no chat.";

/** The API answers errors as `{ error: "<mensagem pt-BR>" }`; the service rethrows the axios response. */
const getErrorMessage = (err: unknown, fallback: string): string =>
  (err as { data?: { error?: string } } | undefined)?.data?.error || fallback;

const showError = (message: string) => setToast({ type: TOAST_TYPE.ERROR, title: "Erro!", message });

export const ConjoChatSettings = observer(function ConjoChatSettings(props: Props) {
  const { projectId, workspaceSlug } = props;
  // states
  const [isCreatingRoom, setIsCreatingRoom] = useState(false);
  const [isSendingTest, setIsSendingTest] = useState(false);
  // integration
  const swrKey = workspaceSlug && projectId ? `PROJECT_CHAT_INTEGRATION_${workspaceSlug}_${projectId}` : null;
  const {
    data: integration,
    error,
    mutate,
  } = useSWR(swrKey, () => chatIntegrationService.retrieve(workspaceSlug, projectId), {
    revalidateOnFocus: false,
  });

  /** Optimistic toggle: shows the new value right away and rolls back if the PATCH fails. */
  const handleUpdate = async (payload: TProjectChatIntegrationUpdate) => {
    if (!integration) return;
    const previous = integration;
    await mutate({ ...previous, ...payload }, false);
    try {
      const response = await chatIntegrationService.update(workspaceSlug, projectId, payload);
      await mutate(response, false);
    } catch (err) {
      await mutate(previous, false);
      showError(getErrorMessage(err, "Não foi possível salvar a alteração. Tente novamente."));
    }
  };

  const handleCreateRoom = async () => {
    const hadRoom = !!integration?.room_id;
    setIsCreatingRoom(true);
    try {
      const response = await chatIntegrationService.createRoom(workspaceSlug, projectId);
      await mutate(response, false);
      setToast({
        type: TOAST_TYPE.SUCCESS,
        title: "Sucesso!",
        message: hadRoom
          ? "Sala atualizada no chat."
          : `Sala ${response?.room_name ? `"${response.room_name}" ` : ""}criada no chat.`,
      });
    } catch (err) {
      showError(getErrorMessage(err, "Não foi possível criar a sala no chat. Tente novamente."));
    } finally {
      setIsCreatingRoom(false);
    }
  };

  const handleSendTest = async () => {
    setIsSendingTest(true);
    try {
      await chatIntegrationService.sendTest(workspaceSlug, projectId);
      setToast({ type: TOAST_TYPE.SUCCESS, title: "Enviado!", message: "Mensagem de teste enviada para a sala." });
    } catch (err) {
      showError(getErrorMessage(err, "Não foi possível enviar a mensagem de teste."));
    } finally {
      setIsSendingTest(false);
    }
  };

  if (error && !integration)
    return (
      <div className="rounded-lg border border-subtle bg-layer-2 px-4 py-3 text-13 text-tertiary">
        {getErrorMessage(error, "Não foi possível carregar a integração com o chat. Recarregue a página.")}
      </div>
    );

  if (!integration)
    return (
      <Loader className="space-y-3">
        <Loader.Item height="56px" width="100%" />
        <Loader.Item height="56px" width="100%" />
        <Loader.Item height="56px" width="100%" />
      </Loader>
    );

  if (!integration.chat_configured)
    return (
      <div className="flex items-start gap-3 rounded-lg border border-subtle bg-layer-2 px-4 py-3">
        <Info className="mt-0.5 size-4 shrink-0 text-tertiary" />
        <p className="text-13 text-secondary">
          O Conjo Chat não está configurado neste servidor. Peça ao administrador para definir as variáveis
          CONJO_CHAT_*.
        </p>
      </div>
    );

  if (!integration.room_id)
    return (
      <div className="space-y-4">
        <div className="rounded-lg border border-subtle bg-layer-2 p-4">
          <h4 className="text-body-sm-medium text-primary">Sala do projeto no chat</h4>
          <p className="mt-1 text-caption-md-regular text-tertiary">
            Crie uma sala no Conjo Chat para este projeto. O bot Tasks publica nela os avisos de tarefas criadas,
            mudanças de estado, atribuições e comentários, e a sala ganha um painel com o board do projeto.
          </p>
          <Button
            className="mt-4"
            variant="primary"
            size="sm"
            loading={isCreatingRoom}
            disabled={isCreatingRoom}
            onClick={() => void handleCreateRoom()}
          >
            Criar sala no chat
          </Button>
        </div>
        <p className="text-caption-md-regular text-tertiary">{HELP_TEXT}</p>
      </div>
    );

  return (
    <ConjoChatRoomSettings
      integration={integration}
      isCreatingRoom={isCreatingRoom}
      isSendingTest={isSendingTest}
      onCreateRoom={() => void handleCreateRoom()}
      onSendTest={() => void handleSendTest()}
      onUpdate={(payload) => void handleUpdate(payload)}
    />
  );
});

type RoomSettingsProps = {
  integration: TProjectChatIntegration;
  isCreatingRoom: boolean;
  isSendingTest: boolean;
  onCreateRoom: () => void;
  onSendTest: () => void;
  onUpdate: (payload: TProjectChatIntegrationUpdate) => void;
};

function ConjoChatRoomSettings(props: RoomSettingsProps) {
  const { integration, isCreatingRoom, isSendingTest, onCreateRoom, onSendTest, onUpdate } = props;

  return (
    <div className="space-y-4">
      <SettingsBoxedControlItem
        title={integration.room_name || integration.room_id}
        description={
          <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <span className="font-mono">{integration.room_id}</span>
            {integration.room_url && (
              <a
                href={integration.room_url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-accent-primary hover:underline"
              >
                Abrir no chat
                <ExternalLink className="size-3" />
              </a>
            )}
          </span>
        }
        control={
          <Button
            variant="secondary"
            size="sm"
            loading={isCreatingRoom}
            disabled={isCreatingRoom}
            onClick={onCreateRoom}
            prependIcon={<RefreshCw />}
          >
            Recriar/atualizar sala
          </Button>
        }
      />

      <SettingsBoxedControlItem
        title="Enviar avisos para a sala"
        description="Quando desativado, nenhum aviso deste projeto é publicado na sala."
        control={
          <ToggleSwitch
            value={integration.enabled}
            onChange={() => onUpdate({ enabled: !integration.enabled })}
            size="sm"
          />
        }
      />

      <div className="space-y-2">
        <h4 className="text-body-sm-medium text-secondary">Avisos enviados</h4>
        {NOTIFY_OPTIONS.map((option) => (
          <SettingsBoxedControlItem
            key={option.key}
            title={option.title}
            description={option.description}
            control={
              <ToggleSwitch
                value={integration[option.key]}
                onChange={() => onUpdate({ [option.key]: !integration[option.key] })}
                size="sm"
              />
            }
          />
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Button
          variant="primary"
          size="sm"
          loading={isSendingTest}
          disabled={isSendingTest}
          onClick={onSendTest}
          prependIcon={<Send />}
        >
          Enviar mensagem de teste
        </Button>
      </div>

      <p className="text-caption-md-regular text-tertiary">{HELP_TEXT}</p>
    </div>
  );
}
