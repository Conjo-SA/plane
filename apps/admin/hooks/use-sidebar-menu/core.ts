/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { BrainCog, Cog, Image, Mail, PlugZap } from "lucide-react";
// plane imports
import { LockIcon, WorkspaceIcon } from "@plane/propel/icons";
// types
import type { TSidebarMenuItem } from "./types";

export type TCoreSidebarMenuKey = "general" | "email" | "workspace" | "authentication" | "ai" | "image" | "mcp";

export const coreSidebarMenuLinks: Record<TCoreSidebarMenuKey, TSidebarMenuItem> = {
  general: {
    Icon: Cog,
    name: "Geral",
    description: "Identifique suas instâncias e veja os principais detalhes.",
    href: `/general/`,
  },
  email: {
    Icon: Mail,
    name: "E-mail",
    description: "Configure seu servidor SMTP.",
    href: `/email/`,
  },
  workspace: {
    Icon: WorkspaceIcon,
    name: "Workspaces",
    description: "Gerencie todos os workspaces desta instância.",
    href: `/workspace/`,
  },
  authentication: {
    Icon: LockIcon,
    name: "Autenticação",
    description: "Configure os métodos de autenticação.",
    href: `/authentication/`,
  },
  ai: {
    Icon: BrainCog,
    name: "Inteligência artificial",
    description: "Configure suas credenciais da OpenAI.",
    href: `/ai/`,
  },
  image: {
    Icon: Image,
    name: "Imagens no Tasks",
    description: "Permita bibliotecas de imagens de terceiros.",
    href: `/image/`,
  },
  mcp: {
    Icon: PlugZap,
    name: "Servidor MCP",
    description: "Conecte assistentes de IA via MCP.",
    href: `/mcp/`,
  },
};
