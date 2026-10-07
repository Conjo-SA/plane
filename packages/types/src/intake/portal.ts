/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { TWorkKind } from "../conjo-billing";
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
  /** Conjo: how the work counts against the client's hour package (list endpoint only). */
  work_kind?: TWorkKind | null;
  /** Conjo: estimate decision, so the list shows what waits for the requester (list endpoint only). */
  budget_status?: "PENDING" | "APPROVED" | "REJECTED" | null;
  budget_hours?: string | null;
  updated_at?: string | null;
};

/**
 * Conjo: hour package of the requester's client. Only sent when the requester
 * is a registered contact of the client. Hours are decimal strings ("37.00").
 */
export type TIntakePortalPackage = {
  client_name: string;
  available: string;
  hours_per_month: string;
  accumulation_months: number;
  next_expiring: { hours: string; expires_on: string | null } | null;
};

export type TIntakePortalTicketList = {
  email: string;
  tickets: TIntakePortalTicket[];
  package?: TIntakePortalPackage | null;
};

export type TIntakePortalTicketComment = {
  id: string;
  comment_html: string;
  created_at: string;
  /** True when the reply was written by the requester from the portal. */
  is_requester: boolean;
  author: string;
};

/**
 * File attached to a ticket, exposed with a portal scoped download route.
 */
export type TIntakePortalTicketAttachment = {
  id: string;
  name: string;
  type: string;
  size: number;
  created_at: string;
  download_url: string;
};

/**
 * Reply submitted by a requester from the portal.
 */
export type TIntakePortalCommentSubmission = {
  comment_html: string;
  attachment_ids?: string[];
};

/**
 * Label applied to a ticket, shown to the requester as its classification.
 */
export type TIntakePortalTicketLabel = {
  name: string;
  color: string;
};

export type TIntakePortalBudgetStatus = "PENDING" | "APPROVED" | "REJECTED";

/**
 * Hourly effort estimate a requester has to approve before the work starts.
 * Approval is one way: it cannot be repeated or revoked. A ticket can have
 * several estimates (a new one after a rejection, an additional one when the
 * scope grows); at most one is pending and the approved ones add up.
 */
export type TIntakePortalBudget = {
  id: string;
  estimated_hours: number;
  note: string;
  status: TIntakePortalBudgetStatus;
  is_approved: boolean;
  is_rejected: boolean;
  requested_at: string | null;
  approved_at: string | null;
  approved_by_email: string | null;
  rejected_at: string | null;
  rejected_by_email: string | null;
  rejection_reason: string;
  /** Conjo: sent, edited by the team (with the previous values), approved or rejected. */
  events?: TIntakePortalBudgetEvent[];
  revision_count?: number;
  /** Only a pending estimate can be edited; an approved one is final. */
  can_edit?: boolean;
};

export type TIntakePortalBudgetEvent = {
  id: string;
  kind: "sent" | "revised" | "approved" | "rejected";
  hours: number;
  note: string;
  previous_hours: number | null;
  previous_note: string;
  note_changed: boolean;
  /** Team member name (team view), "Equipe" (client view) or the client's e-mail. */
  actor: string;
  reason: string;
  occurred_at: string;
};

/**
 * Estimate submitted by the team for the requester to approve.
 */
export type TIntakePortalBudgetSubmission = {
  estimated_hours: number;
  note?: string;
};

/**
 * Team side view of a work item's estimate. Only tickets that came from the
 * portal have a requester who can approve one.
 */
export type TIntakePortalBudgetContext = {
  is_portal_ticket: boolean;
  /** The pending estimate, else the latest. */
  budget: TIntakePortalBudget | null;
  /** Every estimate sent, oldest first. */
  budgets?: TIntakePortalBudget[];
  /** Sum of the approved estimates. */
  approved_hours?: number;
  /** Conjo: who opened the ticket on the portal (reads the public replies). */
  requester?: { name: string; email: string } | null;
};

export type TIntakePortalTicketDetail = TIntakePortalTicket & {
  description_html: string;
  project_identifier: string;
  updated_at: string;
  target_date: string | null;
  completed_at: string | null;
  is_attachment_enabled: boolean;
  labels: TIntakePortalTicketLabel[];
  assignees: string[];
  /** The pending estimate, else the latest. */
  budget: TIntakePortalBudget | null;
  /** Every estimate sent, oldest first. */
  budgets?: TIntakePortalBudget[];
  /** Sum of the approved estimates. */
  approved_hours?: number;
  /** False when the project's client only lets some contacts approve estimates (they debit the package). */
  can_approve_budget?: boolean;
  comments: TIntakePortalTicketComment[];
  attachments: TIntakePortalTicketAttachment[];
};
