/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { API_BASE_URL } from "@plane/constants";
import { Button } from "@plane/propel/button";
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import { mcpService } from "@plane/services";
import type { IMCPServerConfig } from "@plane/types";
import { ToggleSwitch } from "@plane/ui";
import { RefreshCw } from "lucide-react";
import { useState } from "react";
// components
import { CopyField } from "@/components/common/copy-field";

type Props = {
  config: IMCPServerConfig;
  mutateConfig: () => void;
};

export function MCPConnectorConfig(props: Props) {
  const { config, mutateConfig } = props;
  // states
  const [isToggling, setIsToggling] = useState(false);
  const [isRegenerating, setIsRegenerating] = useState(false);

  // derived values
  const apiOrigin = API_BASE_URL || (typeof window !== "undefined" ? window.location.origin : "");
  const serverUrl = `${apiOrigin}/api/mcp/server/`;
  const clientConfigSnippet = JSON.stringify(
    {
      mcpServers: {
        tasks: {
          type: "http",
          url: serverUrl,
          headers: {
            Authorization: `Bearer ${config.token}`,
          },
        },
      },
    },
    null,
    2
  );

  const handleToggle = async (value: boolean) => {
    setIsToggling(true);
    try {
      await mcpService.updateConfig({ is_enabled: value });
      mutateConfig();
      setToast({
        type: TOAST_TYPE.SUCCESS,
        title: value ? "Servidor MCP ativado" : "Servidor MCP desativado",
        message: value
          ? "Clientes MCP agora podem se conectar a esta instância."
          : "Clientes MCP não podem mais se conectar a esta instância.",
      });
    } catch {
      setToast({
        type: TOAST_TYPE.ERROR,
        title: "Erro!",
        message: "Não foi possível atualizar a configuração do servidor MCP. Tente novamente.",
      });
    } finally {
      setIsToggling(false);
    }
  };

  const handleRegenerateToken = async () => {
    setIsRegenerating(true);
    try {
      await mcpService.regenerateToken();
      mutateConfig();
      setToast({
        type: TOAST_TYPE.SUCCESS,
        title: "Token regenerado",
        message: "Atualize todos os clientes MCP conectados com o novo token.",
      });
    } catch {
      setToast({
        type: TOAST_TYPE.ERROR,
        title: "Erro!",
        message: "Não foi possível regenerar o token. Tente novamente.",
      });
    } finally {
      setIsRegenerating(false);
    }
  };

  const handleCopySnippet = () => {
    navigator.clipboard.writeText(clientConfigSnippet);
    setToast({
      type: TOAST_TYPE.INFO,
      title: "Copiado para a área de transferência",
      message: "A configuração do cliente MCP foi copiada para a área de transferência",
    });
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-4">
        <div>
          <div className="text-16 font-medium text-primary">Configuração do conector</div>
          <div className="text-13 text-tertiary">
            Ative o servidor MCP e conecte qualquer cliente compatível com MCP (Claude, Cursor, VS Code etc.).
          </div>
        </div>
        <ToggleSwitch value={config.is_enabled} onChange={handleToggle} size="sm" disabled={isToggling} />
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <CopyField
          label="URL do servidor"
          url={serverUrl}
          description="O endpoint MCP exposto por esta instância. Os clientes enviam requisições JSON-RPC para esta URL."
        />
        <div className="flex items-end gap-2">
          <div className="flex-grow">
            <CopyField
              label="Bearer token"
              url={config.token}
              description="Autentique os clientes com o cabeçalho Authorization: Bearer. Mantenha este token em segredo."
            />
          </div>
          <Button variant="secondary" size="lg" onClick={handleRegenerateToken} disabled={isRegenerating}>
            <RefreshCw className={`h-3.5 w-3.5 ${isRegenerating ? "animate-spin" : ""}`} />
            Regenerar
          </Button>
        </div>
      </div>

      <div className="flex flex-col gap-1">
        <div className="flex items-center justify-between">
          <h4 className="text-13 text-secondary">Configuração do cliente</h4>
          <Button variant="secondary" size="sm" onClick={handleCopySnippet}>
            Copiar
          </Button>
        </div>
        <pre className="overflow-x-auto rounded-md border border-subtle bg-surface-2 p-4 text-12 text-secondary">
          {clientConfigSnippet}
        </pre>
        <div className="text-11 text-tertiary">
          Cole este trecho na configuração do seu cliente MCP (ex.: mcp.json ou claude_desktop_config.json).
        </div>
      </div>
    </div>
  );
}
