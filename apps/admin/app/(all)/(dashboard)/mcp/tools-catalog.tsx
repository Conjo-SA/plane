/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import { mcpService } from "@plane/services";
import type { IMCPServerConfig, IMCPToolDefinition } from "@plane/types";
import { Loader, ToggleSwitch } from "@plane/ui";
import { useState } from "react";
import useSWR from "swr";

type Props = {
  config: IMCPServerConfig;
  mutateConfig: () => void;
};

const CATEGORY_LABELS: Record<string, string> = {
  workspaces: "Workspaces",
  projects: "Projetos",
  members: "Membros",
  work_items: "Tarefas",
  cycles: "Ciclos",
  modules: "Módulos",
  states: "Estados",
  labels: "Etiquetas",
  pages: "Páginas",
  intake: "Entrada",
  time: "Tempo gasto",
  clients: "Clientes e pacotes de horas",
  development: "Desenvolvimento (GitHub)",
  server: "Servidor",
};

export function MCPToolsCatalog(props: Props) {
  const { config, mutateConfig } = props;
  // states
  const [updatingTool, setUpdatingTool] = useState<string | null>(null);
  // fetch tools
  const { data, mutate: mutateTools } = useSWR("MCP_TOOLS_CATALOG", () => mcpService.tools());

  const tools = data?.tools ?? [];
  const toolsByCategory = tools.reduce<Record<string, IMCPToolDefinition[]>>((acc, tool) => {
    const category = tool.category || "general";
    acc[category] = [...(acc[category] ?? []), tool];
    return acc;
  }, {});

  const handleToolToggle = async (tool: IMCPToolDefinition, value: boolean) => {
    setUpdatingTool(tool.name);
    const disabledTools = new Set(config.disabled_tools ?? []);
    if (value) {
      disabledTools.delete(tool.name);
    } else {
      disabledTools.add(tool.name);
    }
    try {
      await mcpService.updateConfig({ disabled_tools: Array.from(disabledTools) });
      mutateConfig();
      mutateTools();
    } catch {
      setToast({
        type: TOAST_TYPE.ERROR,
        title: "Erro!",
        message: `Não foi possível atualizar a ferramenta '${tool.name}'. Tente novamente.`,
      });
    } finally {
      setUpdatingTool(null);
    }
  };

  return (
    <div className="space-y-4">
      <div>
        <div className="text-16 font-medium text-primary">Ferramentas</div>
        <div className="text-13 text-tertiary">
          Escolha quais ferramentas ficam disponíveis para os clientes MCP conectados. Ferramentas desativadas ficam
          ocultas em tools/list e são rejeitadas em tools/call.
        </div>
      </div>

      {!data ? (
        <Loader className="space-y-3">
          <Loader.Item height="40px" />
          <Loader.Item height="40px" />
          <Loader.Item height="40px" />
        </Loader>
      ) : (
        <div className="space-y-6">
          {Object.entries(toolsByCategory).map(([category, categoryTools]) => (
            <div key={category} className="space-y-2">
              <div className="text-13 font-medium text-secondary">
                {CATEGORY_LABELS[category] ?? (category === "general" ? "Geral" : category)}
              </div>
              <div className="divide-y divide-subtle rounded-md border border-subtle">
                {categoryTools.map((tool) => (
                  <div key={tool.name} className="flex items-center justify-between gap-4 px-4 py-3">
                    <div className="min-w-0">
                      <div className="font-mono text-13 text-primary">{tool.name}</div>
                      <div className="text-12 text-tertiary">{tool.description}</div>
                    </div>
                    <ToggleSwitch
                      value={tool.is_enabled}
                      onChange={(value) => handleToolToggle(tool, value)}
                      size="sm"
                      disabled={updatingTool === tool.name}
                    />
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
