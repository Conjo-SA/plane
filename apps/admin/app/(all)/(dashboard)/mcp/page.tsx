/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
import useSWR from "swr";
import { mcpService } from "@plane/services";
import { Loader } from "@plane/ui";
// components
import { PageWrapper } from "@/components/common/page-wrapper";
// types
import type { Route } from "./+types/page";
// local
import { MCPCallLogs } from "./call-logs";
import { MCPConnectorConfig } from "./connector-config";
import { MCPTestConnection } from "./test-connection";
import { MCPToolsCatalog } from "./tools-catalog";

const MCPServerPage = observer(function MCPServerPage(_props: Route.ComponentProps) {
  const { data: config, mutate: mutateConfig } = useSWR("MCP_SERVER_CONFIG", () => mcpService.config());

  return (
    <PageWrapper
      header={{
        title: "MCP server",
        description:
          "Expose this Plane instance over the Model Context Protocol so AI assistants can read and write workspaces, projects and work items.",
      }}
    >
      {config ? (
        <div className="space-y-10">
          <MCPConnectorConfig config={config} mutateConfig={mutateConfig} />
          <MCPTestConnection />
          <MCPToolsCatalog config={config} mutateConfig={mutateConfig} />
          <MCPCallLogs />
        </div>
      ) : (
        <Loader className="space-y-8">
          <Loader.Item height="50px" width="40%" />
          <div className="grid w-2/3 grid-cols-2 gap-x-8 gap-y-4">
            <Loader.Item height="50px" />
            <Loader.Item height="50px" />
          </div>
          <Loader.Item height="50px" width="20%" />
        </Loader>
      )}
    </PageWrapper>
  );
});

export const meta: Route.MetaFunction = () => [{ title: "MCP Server Settings - God Mode" }];

export default MCPServerPage;
