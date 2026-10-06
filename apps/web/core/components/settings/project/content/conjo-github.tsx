/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { Check, ChevronDown, Copy, Info, X } from "lucide-react";
import { observer } from "mobx-react";
import useSWR from "swr";
// plane imports
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import { GitHubIntegrationService } from "@plane/services";
import type { TProjectGitHubSettings, TProjectGitHubSettingsUpdate } from "@plane/types";
import { Loader, ToggleSwitch } from "@plane/ui";
// components
import { StateDropdown } from "@/components/dropdowns/state/dropdown";
import { SettingsBoxedControlItem } from "@/components/settings/boxed-control-item";
// hooks
import { useProjectState } from "@/hooks/store/use-project-state";
// local imports
import { useCopyText } from "./use-copy-text";

const githubIntegrationService = new GitHubIntegrationService();

type Props = {
  projectId: string;
  workspaceSlug: string;
};

type TAutomationKey = "pr_opened_state" | "pr_merged_state";

const AUTOMATIONS: { key: TAutomationKey; title: string; description: string }[] = [
  {
    key: "pr_opened_state",
    title: "Pull request aberto",
    description: "Move a tarefa para este estado quando um PR que a cita é aberto (rascunhos não contam).",
  },
  {
    key: "pr_merged_state",
    title: "Pull request mergeado",
    description: "Move a tarefa para este estado quando o PR é mergeado.",
  },
];

/** The API answers errors as `{ error: "<mensagem pt-BR>" }`; the service rethrows the axios response. */
const getErrorMessage = (err: unknown, fallback: string): string =>
  (err as { data?: { error?: string } } | undefined)?.data?.error || fallback;

const formatDateTime = (value: string) => {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("pt-BR");
};

export const GitHubSettings = observer(function GitHubSettings(props: Props) {
  const { projectId, workspaceSlug } = props;
  // store hooks
  const { fetchProjectStates, getStateById } = useProjectState();
  useSWR(workspaceSlug && projectId ? `PROJECT_STATES_${workspaceSlug}_${projectId}` : null, () =>
    fetchProjectStates(workspaceSlug, projectId)
  );
  const swrKey = workspaceSlug && projectId ? `PROJECT_GITHUB_SETTINGS_${workspaceSlug}_${projectId}` : null;
  const {
    data: settings,
    error,
    mutate,
  } = useSWR(swrKey, () => githubIntegrationService.retrieveSettings(workspaceSlug, projectId), {
    revalidateOnFocus: false,
  });

  /** Optimistic update: shows the new value right away and rolls back if the PATCH fails. */
  const handleUpdate = async (payload: TProjectGitHubSettingsUpdate) => {
    if (!settings) return;
    const previous = settings;
    await mutate({ ...previous, ...payload }, false);
    try {
      const response = await githubIntegrationService.updateSettings(workspaceSlug, projectId, payload);
      await mutate(response, false);
    } catch (err) {
      await mutate(previous, false);
      setToast({
        type: TOAST_TYPE.ERROR,
        title: "Erro!",
        message: getErrorMessage(err, "Não foi possível salvar a alteração. Tente novamente."),
      });
    }
  };

  if (error && !settings)
    return (
      <div className="rounded-lg border border-subtle bg-layer-2 px-4 py-3 text-13 text-tertiary">
        {getErrorMessage(error, "Não foi possível carregar a integração com o GitHub. Recarregue a página.")}
      </div>
    );

  if (!settings)
    return (
      <Loader className="space-y-3">
        <Loader.Item height="56px" width="100%" />
        <Loader.Item height="56px" width="100%" />
        <Loader.Item height="56px" width="100%" />
      </Loader>
    );

  return (
    <div className="space-y-6">
      <WebhookStatus settings={settings} />
      <HowToLink identifier={settings.project_identifier} />

      <SettingsBoxedControlItem
        title="Smart commits"
        description={
          <>
            Comandos na mensagem do commit, depois da chave: <code>#comment texto</code> adiciona um comentário e{" "}
            <code>#done</code>, <code>#em-revisao</code> ou o nome de qualquer estado move a tarefa. Valem para quem
            commita com o mesmo e-mail da conta no Tasks.
          </>
        }
        control={
          <ToggleSwitch
            value={settings.smart_commits}
            onChange={() => void handleUpdate({ smart_commits: !settings.smart_commits })}
            size="sm"
          />
        }
      />

      <div className="space-y-2">
        <h4 className="text-body-sm-medium text-secondary">Automações de pull request</h4>
        {AUTOMATIONS.map((automation) => (
          <SettingsBoxedControlItem
            key={automation.key}
            title={automation.title}
            description={automation.description}
            control={
              <div className="flex items-center gap-1">
                <StateDropdown
                  projectId={projectId}
                  value={settings[automation.key]}
                  onChange={(stateId) => void handleUpdate({ [automation.key]: stateId })}
                  buttonVariant="border-with-text"
                  showDefaultState={false}
                  button={
                    <span className="flex items-center gap-1.5 rounded-sm border border-subtle px-2 py-1 text-12 text-secondary">
                      {getStateById(settings[automation.key])?.name ?? "Não mover"}
                      <ChevronDown className="size-3" />
                    </span>
                  }
                />
                {settings[automation.key] && (
                  <button
                    type="button"
                    className="rounded-sm p-1 text-tertiary hover:bg-layer-1 hover:text-primary"
                    onClick={() => void handleUpdate({ [automation.key]: null })}
                    aria-label="Não mover"
                    title="Não mover"
                  >
                    <X className="size-3.5" />
                  </button>
                )}
              </div>
            }
          />
        ))}
      </div>
    </div>
  );
});

function WebhookStatus({ settings }: { settings: TProjectGitHubSettings }) {
  const { copied, copy } = useCopyText();

  if (!settings.webhook_configured)
    return (
      <div className="flex items-start gap-3 rounded-lg border border-subtle bg-layer-2 px-4 py-3">
        <Info className="mt-0.5 size-4 shrink-0 text-tertiary" />
        <p className="text-13 text-secondary">
          O GitHub não está configurado neste servidor. Peça ao administrador para definir a variável
          CONJO_GITHUB_WEBHOOK_SECRET e criar o webhook na organização do GitHub.
        </p>
      </div>
    );

  return (
    <div className="rounded-lg border border-subtle bg-layer-2 p-4">
      <h4 className="text-body-sm-medium text-primary">Webhook do GitHub</h4>
      <p className="mt-1 text-caption-md-regular text-tertiary">
        O webhook fica na organização do GitHub e vale para todos os projetos do Tasks.
      </p>
      <div className="mt-3 flex items-center gap-2">
        <code className="truncate rounded-sm bg-layer-1 px-2 py-1 text-12">{settings.webhook_url}</code>
        <button
          type="button"
          className="rounded-sm p-1 text-tertiary hover:bg-layer-1 hover:text-primary"
          onClick={() => void copy(settings.webhook_url)}
          aria-label="Copiar URL"
          title="Copiar URL"
        >
          {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
        </button>
      </div>
      <p className="mt-2 text-caption-md-regular text-tertiary">
        {settings.last_event
          ? `Último evento recebido: ${settings.last_event.event}${
              settings.last_event.repository ? ` em ${settings.last_event.repository}` : ""
            } · ${formatDateTime(settings.last_event.at)}`
          : "Nenhum evento recebido ainda."}
      </p>
    </div>
  );
}

function HowToLink({ identifier }: { identifier: string }) {
  const key = `${identifier}-12`;
  const examples = [
    { label: "Branch", value: `${identifier.toLowerCase()}-12-corrigir-login` },
    { label: "Commit", value: `${key}: corrige validação do login` },
    { label: "Pull request", value: `${key} Corrige login` },
  ];
  return (
    <div className="rounded-lg border border-subtle p-4">
      <h4 className="text-body-sm-medium text-primary">Como vincular</h4>
      <p className="mt-1 text-caption-md-regular text-tertiary">
        Use a chave da tarefa no nome da branch, na mensagem do commit ou no título do pull request. Eles aparecem na
        tarefa, na seção Desenvolvimento.
      </p>
      <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-12">
        {examples.map((example) => (
          <div key={example.label} className="contents">
            <dt className="text-tertiary">{example.label}</dt>
            <dd>
              <code className="rounded-sm bg-layer-1 px-1.5 py-0.5">{example.value}</code>
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
