/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

/** Conjo (MAN-467): areas of the workspace with their own access rule. */
export type TWorkspaceArea = "clients" | "docs" | "time" | "integrations" | "archives";

/** Workspace roles that can be granted an area (the admin, 20, always enters). */
export type TWorkspaceAreaRole = 15 | 5;

/** Areas the current user enters. */
export type TMyWorkspaceAreas = {
  areas: Record<TWorkspaceArea, boolean>;
};

export type TWorkspaceAreaRule = {
  key: TWorkspaceArea;
  label: string;
  allowed_roles: TWorkspaceAreaRole[];
  default_roles: TWorkspaceAreaRole[];
  is_default: boolean;
};

export type TWorkspaceAreaOverride = {
  id: string;
  area: TWorkspaceArea;
  allow: boolean;
  role: number;
  member: {
    id: string;
    display_name: string;
    email: string;
    avatar_url: string;
  };
};

export type TWorkspaceAreaConfiguration = {
  areas: TWorkspaceAreaRule[];
  overrides: TWorkspaceAreaOverride[];
};

export type TWorkspaceAreaOverrideCreate = {
  area: TWorkspaceArea;
  member_id: string;
  allow: boolean;
};
