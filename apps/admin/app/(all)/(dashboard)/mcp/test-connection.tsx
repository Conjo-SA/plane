/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { CircleCheck, CircleX, PlugZap } from "lucide-react";
import { Button } from "@plane/propel/button";
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import { mcpService } from "@plane/services";
import type { IMCPTestConnectionResult } from "@plane/types";

export function MCPTestConnection() {
  // states
  const [isTesting, setIsTesting] = useState(false);
  const [result, setResult] = useState<IMCPTestConnectionResult | null>(null);

  const handleTestConnection = async () => {
    setIsTesting(true);
    setResult(null);
    await mcpService
      .testConnection()
      .then((response) => setResult(response))
      .catch(() =>
        setToast({
          type: TOAST_TYPE.ERROR,
          title: "Falha no teste de conexão",
          message: "Não foi possível concluir o handshake MCP. Verifique a configuração do servidor.",
        })
      )
      .finally(() => setIsTesting(false));
  };

  return (
    <div className="space-y-4">
      <div>
        <div className="text-16 font-medium text-primary">Teste de conexão</div>
        <div className="text-13 text-tertiary">
          Executa um handshake MCP sintético (initialize + tools/list) contra o servidor local.
        </div>
      </div>

      <div className="flex items-center gap-4">
        <Button variant="primary" size="lg" onClick={handleTestConnection} loading={isTesting}>
          {!isTesting && <PlugZap className="h-3.5 w-3.5" />}
          {isTesting ? "Testando" : "Testar conexão"}
        </Button>
        {result && (
          <div className="flex items-center gap-2 text-13">
            {result.success ? (
              <>
                <CircleCheck className="h-4 w-4 text-success-primary" />
                <span className="text-primary">
                  Handshake OK — protocolo {result.protocol_version}, {result.tool_count} ferramentas ativas,{" "}
                  {result.latency_ms} ms
                </span>
              </>
            ) : (
              <>
                <CircleX className="h-4 w-4 text-danger-primary" />
                <span className="text-primary">Falha no handshake</span>
              </>
            )}
          </div>
        )}
      </div>

      {result && !result.is_enabled && (
        <div className="rounded-sm border border-warning-subtle bg-warning-subtle px-4 py-2 text-caption-sm-regular text-warning-primary">
          O servidor MCP está desativado. Ative-o acima antes de conectar clientes.
        </div>
      )}
    </div>
  );
}
