/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import useSWR, { mutate as globalMutate } from "swr";
// plane imports
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import { Tooltip } from "@plane/propel/tooltip";
import { CustomSearchSelect } from "@plane/ui";
import { cn } from "@plane/utils";
// components
import { conjoBillingService, getErrorMessage } from "@/components/conjo-clients/helpers";
import { getIssueTimeSWRKey } from "@/components/issues/issue-detail-widgets/time";
// local imports
import type { TIssueOperations } from "../root";
import { getProjectClientSummarySWRKey } from "./card-chip";

/** SWR keys of the work item's client and of the workspace's client options. */
export const getIssueClientSWRKey = (issueId: string) => `ISSUE_CLIENT_${issueId}`;
export const getClientOptionsSWRKey = (workspaceSlug: string) => `CONJO_CLIENT_OPTIONS_${workspaceSlug}`;

/** Option value for "Sem cliente" (the select needs a non-null value). */
const NO_CLIENT = "__no_client__";

type Props = {
  className?: string;
  workspaceSlug: string;
  projectId: string;
  issueId: string;
  issueOperations: TIssueOperations;
  disabled?: boolean;
};

/** "Cliente" property of the work item: chosen on the card, or inherited from the project. */
export function IssueClientSelect(props: Props) {
  const { className = "", workspaceSlug, projectId, issueId, issueOperations, disabled = false } = props;
  const [isUpdating, setIsUpdating] = useState(false);
  const { data, mutate } = useSWR(
    workspaceSlug && projectId && issueId ? getIssueClientSWRKey(issueId) : null,
    () => conjoBillingService.getIssueClient(workspaceSlug, projectId, issueId),
    { revalidateOnFocus: true }
  );
  const canChange = !!data?.can_change && !disabled;
  const { data: options } = useSWR(
    canChange ? getClientOptionsSWRKey(workspaceSlug) : null,
    () => conjoBillingService.getClientOptions(workspaceSlug),
    { revalidateOnFocus: false }
  );

  const client = data?.client ?? null;
  const inherited = client?.via === "project";

  const handleChange = async (value: string) => {
    const clientId = value === NO_CLIENT ? null : value;
    const current = client?.via === "card" ? client.id : null;
    if (!canChange || isUpdating || clientId === current) return;
    setIsUpdating(true);
    try {
      await mutate(await conjoBillingService.setIssueClient(workspaceSlug, projectId, issueId, clientId), {
        revalidate: false,
      });
      void globalMutate(getIssueTimeSWRKey(issueId));
      void globalMutate(getProjectClientSummarySWRKey(projectId));
      // the backend keeps the client's board label in sync, so reload the work item's labels
      void issueOperations.fetch(workspaceSlug, projectId, issueId);
      setToast({
        type: TOAST_TYPE.SUCCESS,
        title: "Cliente alterado",
        message: clientId ? "O card passa a contar para o cliente escolhido." : "O cliente do card foi removido.",
      });
    } catch (err) {
      setToast({
        type: TOAST_TYPE.ERROR,
        title: "Erro",
        message: getErrorMessage(err, "Não foi possível alterar o cliente."),
      });
    } finally {
      setIsUpdating(false);
    }
  };

  const label = client ? (
    <span className={cn("flex min-w-0 items-center gap-1 truncate", { "text-tertiary": inherited })}>
      <span className="truncate">{client.name}</span>
      {inherited && <span className="shrink-0 text-caption-sm-regular text-placeholder">· pelo projeto</span>}
    </span>
  ) : (
    <span className="truncate text-placeholder">Sem cliente</span>
  );
  const button = (
    <Tooltip
      tooltipHeading="Cliente"
      tooltipContent={inherited ? "Herdado do projeto: o projeto inteiro é deste cliente." : null}
      disabled={!inherited}
    >
      <span className="flex h-7.5 w-full min-w-0 items-center px-2 text-body-xs-regular">{label}</span>
    </Tooltip>
  );

  if (!data) return <div className={cn("h-7.5", className)} />;

  if (!canChange) return <div className={cn("flex min-w-0 items-center", className)}>{button}</div>;

  const projectClient = data.project_client;
  const selectOptions = [
    {
      value: NO_CLIENT,
      query: "sem cliente",
      content: <span className="text-placeholder">Sem cliente</span>,
      tooltip: projectClient ? `Usa o cliente do projeto (${projectClient.name}).` : undefined,
    },
    ...(options?.clients ?? []).map((option) => ({
      value: option.id,
      query: option.name,
      content: <span className="truncate">{option.name}</span>,
    })),
  ];

  return (
    <CustomSearchSelect
      className={cn("min-w-0", className)}
      customButtonClassName="h-7.5 rounded-sm text-left"
      customButton={button}
      value={client?.via === "card" ? client.id : NO_CLIENT}
      onChange={(value: string) => void handleChange(value)}
      options={options ? selectOptions : undefined}
      disabled={isUpdating}
      noResultsMessage="Nenhum cliente encontrado"
      maxHeight="lg"
    />
  );
}
