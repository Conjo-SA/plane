/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { TIssuePriorities } from "../issues";

/**
 * Request form configuration of a project, managed from the project settings.
 */
export type TIntakePortal = {
    id: string;
    anchor: string;
    is_enabled: boolean;
    title: string;
    description: string;
    success_message: string;
    is_attachment_enabled: boolean;
    intake: string;
    project: string;
    workspace: string;
};

/**
 * Public presentation data of a request form, exposed without authentication.
 */
export type TIntakePortalMeta = {
    anchor: string;
    title: string;
    description: string;
    success_message: string;
    is_attachment_enabled: boolean;
    project_name: string;
    workspace_name: string;
    logo_props: Record<string, unknown>;
};

/**
 * Payload submitted by an external requester through the public request form.
 */
export type TIntakePortalSubmission = {
    name: string;
    description_html: string;
    priority: TIssuePriorities;
    requester_name: string;
    requester_email: string;
};

export type TIntakePortalSubmissionResponse = {
    id: string;
    sequence_id: number;
    success_message: string;
};
