/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { RefreshCw } from "lucide-react";
import { API_BASE_URL } from "@plane/constants";
import { Button } from "@plane/propel/button";
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import { mcpService } from "@plane/services";
import type { IMCPServerConfig } from "@plane/types";
import { ToggleSwitch } from "@plane/ui";
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
        plane: {
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
        title: value ? "MCP server enabled" : "MCP server disabled",
        message: value
          ? "MCP clients can now connect to this instance."
          : "MCP clients can no longer connect to this instance.",
      });
    } catch {
      setToast({
        type: TOAST_TYPE.ERROR,
        title: "Error",
        message: "Could not update the MCP server configuration. Please try again.",
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
        title: "Token regenerated",
        message: "Update every connected MCP client with the new token.",
      });
    } catch {
      setToast({
        type: TOAST_TYPE.ERROR,
        title: "Error",
        message: "Could not regenerate the token. Please try again.",
      });
    } finally {
      setIsRegenerating(false);
    }
  };

  const handleCopySnippet = () => {
    navigator.clipboard.writeText(clientConfigSnippet);
    setToast({
      type: TOAST_TYPE.INFO,
      title: "Copied to clipboard",
      message: "The MCP client configuration has been copied to your clipboard",
    });
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-4">
        <div>
          <div className="text-16 font-medium text-primary">Connector configuration</div>
          <div className="text-13 text-tertiary">
            Enable the MCP server and connect any MCP-compatible client (Claude, Cursor, VS Code, etc.).
          </div>
        </div>
        <ToggleSwitch value={config.is_enabled} onChange={handleToggle} size="sm" disabled={isToggling} />
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <CopyField
          label="Server URL"
          url={serverUrl}
          description="The MCP endpoint exposed by this instance. Clients send JSON-RPC requests to this URL."
        />
        <div className="flex items-end gap-2">
          <div className="flex-grow">
            <CopyField
              label="Bearer token"
              url={config.token}
              description="Authenticate clients with the Authorization: Bearer header. Keep this token secret."
            />
          </div>
          <Button variant="secondary" size="lg" onClick={handleRegenerateToken} disabled={isRegenerating}>
            <RefreshCw className={`h-3.5 w-3.5 ${isRegenerating ? "animate-spin" : ""}`} />
            Rotate
          </Button>
        </div>
      </div>

      <div className="flex flex-col gap-1">
        <div className="flex items-center justify-between">
          <h4 className="text-13 text-secondary">Client configuration</h4>
          <Button variant="secondary" size="sm" onClick={handleCopySnippet}>
            Copy
          </Button>
        </div>
        <pre className="overflow-x-auto rounded-md border border-subtle bg-surface-2 p-4 text-12 text-secondary">
          {clientConfigSnippet}
        </pre>
        <div className="text-11 text-tertiary">
          Paste this snippet into your MCP client configuration (e.g. mcp.json or claude_desktop_config.json).
        </div>
      </div>
    </div>
  );
}
