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
          title: "Connection test failed",
          message: "The MCP handshake could not be completed. Check the server configuration.",
        })
      )
      .finally(() => setIsTesting(false));
  };

  return (
    <div className="space-y-4">
      <div>
        <div className="text-16 font-medium text-primary">Connection test</div>
        <div className="text-13 text-tertiary">
          Run a synthetic MCP handshake (initialize + tools/list) against the in-process server.
        </div>
      </div>

      <div className="flex items-center gap-4">
        <Button variant="primary" size="lg" onClick={handleTestConnection} loading={isTesting}>
          {!isTesting && <PlugZap className="h-3.5 w-3.5" />}
          {isTesting ? "Testing" : "Test connection"}
        </Button>
        {result && (
          <div className="flex items-center gap-2 text-13">
            {result.success ? (
              <>
                <CircleCheck className="h-4 w-4 text-success-primary" />
                <span className="text-primary">
                  Handshake OK — protocol {result.protocol_version}, {result.tool_count} tools enabled,{" "}
                  {result.latency_ms} ms
                </span>
              </>
            ) : (
              <>
                <CircleX className="h-4 w-4 text-danger-primary" />
                <span className="text-primary">Handshake failed</span>
              </>
            )}
          </div>
        )}
      </div>

      {result && !result.is_enabled && (
        <div className="rounded-sm border border-warning-subtle bg-warning-subtle px-4 py-2 text-caption-sm-regular text-warning-primary">
          The MCP server is currently disabled. Enable it above before connecting clients.
        </div>
      )}
    </div>
  );
}
