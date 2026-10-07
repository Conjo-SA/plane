/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { Button } from "@plane/propel/button";
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import { mcpService } from "@plane/services";
import { Loader } from "@plane/ui";
import { RefreshCw, Trash2 } from "lucide-react";
import { useState } from "react";
import useSWR from "swr";

export function MCPCallLogs() {
  // states
  const [isClearing, setIsClearing] = useState(false);
  // fetch logs
  const { data, mutate: mutateLogs } = useSWR("MCP_TOOL_CALL_LOGS", () => mcpService.logs(50), {
    refreshInterval: 15000,
  });

  const logs = data?.logs ?? [];

  const handleClearLogs = async () => {
    setIsClearing(true);
    try {
      await mcpService.clearLogs();
      mutateLogs();
      setToast({
        type: TOAST_TYPE.SUCCESS,
        title: "Logs limpos",
        message: "Todos os logs de chamadas de ferramentas MCP foram excluídos.",
      });
    } catch {
      setToast({
        type: TOAST_TYPE.ERROR,
        title: "Erro!",
        message: "Não foi possível limpar os logs. Tente novamente.",
      });
    } finally {
      setIsClearing(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-4">
        <div>
          <div className="text-16 font-medium text-primary">Logs de chamadas</div>
          <div className="text-13 text-tertiary">
            Últimas chamadas de ferramentas atendidas pelo servidor MCP. Atualiza automaticamente a cada 15 segundos.
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="secondary" size="sm" onClick={() => mutateLogs()}>
            <RefreshCw className="h-3.5 w-3.5" />
            Atualizar
          </Button>
          <Button variant="secondary" size="sm" onClick={handleClearLogs} disabled={isClearing || logs.length === 0}>
            <Trash2 className="h-3.5 w-3.5" />
            Limpar
          </Button>
        </div>
      </div>

      {!data ? (
        <Loader className="space-y-3">
          <Loader.Item height="40px" />
          <Loader.Item height="40px" />
        </Loader>
      ) : logs.length === 0 ? (
        <div className="rounded-md border border-subtle px-4 py-6 text-center text-13 text-tertiary">
          Nenhuma chamada de ferramenta ainda.
        </div>
      ) : (
        <div className="overflow-x-auto rounded-md border border-subtle">
          <table className="w-full text-left text-13">
            <thead className="border-b border-subtle bg-surface-2 text-12 text-tertiary">
              <tr>
                <th className="px-4 py-2 font-medium">Ferramenta</th>
                <th className="px-4 py-2 font-medium">Status</th>
                <th className="px-4 py-2 font-medium">Duração</th>
                <th className="px-4 py-2 font-medium">Quando</th>
                <th className="px-4 py-2 font-medium">Detalhes</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-subtle">
              {logs.map((log) => (
                <tr key={log.id}>
                  <td className="font-mono px-4 py-2 text-primary">{log.tool_name}</td>
                  <td className="px-4 py-2">
                    <span
                      className={
                        log.status === "success"
                          ? "font-medium text-success-primary"
                          : "font-medium text-danger-primary"
                      }
                    >
                      {log.status === "success" ? "sucesso" : log.status === "error" ? "erro" : log.status}
                    </span>
                  </td>
                  <td className="px-4 py-2 text-secondary">{log.duration_ms} ms</td>
                  <td className="px-4 py-2 text-secondary">{new Date(log.created_at).toLocaleString("pt-BR")}</td>
                  <td className="max-w-64 truncate px-4 py-2 text-tertiary">
                    {log.status === "error" ? log.error_message : JSON.stringify(log.arguments)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
