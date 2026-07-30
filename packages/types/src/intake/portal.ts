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
    slug: string | null;
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
 * Label applied to every work item submitted through a tagged portal URL.
 */
export type TIntakePortalTag = {
    id: string;
    name: string;
    color: string;
};

/**
 * Public presentation data of a request form, exposed without authentication.
 */
export type TIntakePortalMeta = {
    anchor: string;
    slug: string | null;
    title: string;
    description: string;
    success_message: string;
    is_attachment_enabled: boolean;
    project_name: string;
    workspace_name: string;
    logo_props: Record<string, unknown>;
    tag: TIntakePortalTag | null;
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
    tag?: string;
    attachment_ids?: string[];
};

export type TIntakePortalSubmissionResponse = {
    id: string;
    sequence_id: number;
    success_message: string;
};

/**
 * Presigned contract returned by the API so the browser can upload an
 * attachment straight to object storage.
 */
export type TIntakePortalAssetUpload = {
    asset_id: string;
    upload_data: {
        url: string;
        fields: Record<string, string>;
    };
};
/**
 * Session issued to a requester after confirming ownership of their email.
 */
export type TIntakePortalSession = {
    token: string;
    email: string;
};

/**
 * Ticket summary shown in the requester portal.
 */
export type TIntakePortalTicket = {
    id: string;
    name: string;
    sequence_id: number;
    priority: TIssuePriorities;
    created_at: string;
    project_name: string;
    state: string | null;
    state_group: string | null;
    intake_status: number;
};

export type TIntakePortalTicketList = {
    email: string;
    tickets: TIntakePortalTicket[];
};

export type TIntakePortalTicketComment = {
    id: string;
    comment_html: string;
    created_at: string;
};

export type TIntakePortalTicketDetail = TIntakePortalTicket & {
    description_html: string;
    comments: TIntakePortalTicketComment[];
};