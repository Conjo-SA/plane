/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

/** Hours are decimal strings ("8.00"); minutes are integers. */

export type TWorkKind = "evolution" | "maintenance" | "internal";

export type TUserLite = { id: string; display_name: string; avatar_url: string };

export type TIssueWorkLog = {
  id: string;
  minutes: number;
  logged_on: string;
  description: string;
  source: "manual" | "commit" | "chat";
  member: TUserLite | null;
  created_at: string | null;
};

export type TIssueTime = {
  entries: TIssueWorkLog[];
  total_minutes: number;
  kind: TWorkKind | null;
  budget: {
    hours: string;
    status: "PENDING" | "APPROVED" | "REJECTED";
    approved_by_email: string | null;
    approved_at: string | null;
  } | null;
  /** Hours debited from the client's package for this work item (open debit), if any. */
  debited_hours: string | null;
  /** Client the work item counts for: chosen on the card, otherwise inherited from its project. */
  client: TIssueClientRef | null;
};

/** A client in a short form (id and name). */
export type TClientOption = { id: string; name: string };

/** Client of a work item: chosen on the card ("card") or inherited from its project ("project"). */
export type TIssueClientRef = TClientOption & { via: "card" | "project" };

export type TIssueClient = {
  client: TIssueClientRef | null;
  /** Client the whole project belongs to, if any (fallback when the card has none). */
  project_client: TClientOption | null;
  /** False for guests, or when an approved estimate requires a workspace admin to change it. */
  can_change: boolean;
};

/** Clients of a project's work items: only the ones chosen on the card, by work item id. */
export type TProjectClientSummary = {
  project_client: TClientOption | null;
  issues: Record<string, TClientOption>;
};

// "description" (o que foi feito) é obrigatória em lançamentos manuais.
export type TIssueTimeCreate = { duration: string; logged_on?: string; description: string };
export type TIssueTimeUpdate = Partial<TIssueTimeCreate>;

export type THourLot = {
  id: string;
  kind: "credit" | "adjustment";
  period: string | null;
  hours: string;
  remaining: string;
  expires_on: string | null;
};

export type TPackageSummary = {
  contract_id: string;
  contract_name: string;
  hours_per_month: string;
  accumulation_months: number;
  max_balance: string;
  available: string;
  debited_this_month: string;
  low_balance: boolean;
  /** Hours that expire on the first expiry date (all lots sharing it), or null without lots. */
  next_expiring?: { hours: string; expires_on: string | null } | null;
  /** Valid lots, the one that expires first first. */
  lots: THourLot[];
};

export type TClientContact = {
  id: string;
  name: string;
  email: string;
  phone: string;
  role: string;
  can_approve: boolean;
};

export type TClientContract = {
  id: string;
  name: string;
  hours_per_month: string;
  accumulation_months: number;
  credit_day: number;
  starts_on: string;
  ends_on: string | null;
  low_balance_percent: number;
  is_active: boolean;
};

export type TClientContractCreate = Omit<TClientContract, "id" | "is_active"> & {
  is_active?: boolean;
  /** Hours the client already has when the contract is registered (becomes an adjustment). */
  opening_balance?: string;
};

/** A label (of a shared board, e.g. MAN) whose work items count for the client. */
export type TClientLabel = {
  id: string;
  name: string;
  color: string;
  project_id: string;
  project_identifier: string;
};

/** A workspace label offered in the picker, with the client it already belongs to (a label has one client). */
export type TClientLabelOption = TClientLabel & {
  project_name: string;
  client: { id: string; name: string } | null;
};

export type TClientListItem = {
  id: string;
  name: string;
  legal_name: string;
  document: string;
  is_active: boolean;
  package: TPackageSummary | null;
  project_ids: string[];
  labels: TClientLabel[];
};

export type TClient = TClientListItem & {
  notes: string;
  contacts: TClientContact[];
  contracts: TClientContract[];
  projects: { id: string; identifier: string; name: string }[];
  maintenance_minutes_this_month: number;
  created_at: string | null;
};

export type TClientCreate = Pick<TClient, "name"> & Partial<Pick<TClient, "legal_name" | "document" | "notes">>;
export type TClientUpdate = Partial<Pick<TClient, "name" | "legal_name" | "document" | "notes" | "is_active">>;
export type TClientContactInput = Partial<Omit<TClientContact, "id">> & { name?: string };

export type THourLedgerKind = "credit" | "debit" | "expiration" | "reversal" | "adjustment" | "excess";

export type TIssueRef = { id: string; project_id: string; key: string; name: string };

export type THourLedgerEntry = {
  id: string;
  kind: THourLedgerKind;
  /** Signed effect on the balance; for "excess" the (positive) hours beyond the balance. */
  hours: string;
  occurred_on: string;
  note: string;
  /** Balance right after this entry. */
  balance: string;
  issue: TIssueRef | null;
  period: string | null;
  expires_on: string | null;
  lots: string[];
  /** Months (YYYY-MM-01) of the credits a debit/expiration used. */
  lot_periods: string[];
  reversed: boolean;
  exported_at: string | null;
  author: TUserLite | null;
};

export type TClientLedger = {
  package: TPackageSummary | null;
  contract?: TClientContract;
  entries: THourLedgerEntry[];
};

export type TClientTimelineType = "requests" | "hours" | "contacts" | "deliveries";

export type TClientNoteKind = "meeting" | "call" | "email" | "note";

export type TClientTimelineEvent =
  | { at: string; type: "note"; id: string; kind: TClientNoteKind; body: string; contacts: string[]; author: string }
  | {
      at: string;
      type: "ledger";
      id: string;
      kind: THourLedgerKind;
      hours: string;
      note: string;
      expires_on: string | null;
      issue: TIssueRef | null;
    }
  | { at: string; type: "request"; issue: TIssueRef; requester: string }
  | { at: string; type: "estimate_sent"; issue: TIssueRef; hours: string }
  | { at: string; type: "estimate_approved"; issue: TIssueRef; hours: string; by: string }
  | { at: string; type: "estimate_rejected"; issue: TIssueRef; hours: string; by: string; reason: string }
  | {
      at: string;
      type: "delivered";
      issue: TIssueRef;
      kind: TWorkKind | null;
      minutes: number;
      estimated_hours: string | null;
    }
  | {
      at: string;
      type: "pr_merged";
      issue: TIssueRef;
      number: string;
      title: string;
      url: string;
      repository: string;
      author: string;
    };

export type TClientTimeline = { events: TClientTimelineEvent[]; next_before: string | null };

export type TClientNoteCreate = {
  kind: TClientNoteKind;
  body: string;
  occurred_at?: string;
  contact_ids?: string[];
};

/** Conjo: time a work item spent in each state (board column), until done. */
export type TIssueStateRef = {
  state_id: string | null;
  name: string;
  color: string;
  group: string | null;
};

export type TIssueStateSegment = TIssueStateRef & {
  started_at: string;
  /** null for the current state. */
  ended_at: string | null;
  /** null for the final completed/cancelled state (the clock stopped there). */
  seconds: number | null;
};

export type TIssueStateTimeline = {
  segments: TIssueStateSegment[];
  totals: (TIssueStateRef & { seconds: number })[];
  created_at: string;
  current: TIssueStateRef;
  current_since: string;
  is_done: boolean;
  done_at: string | null;
  /** From creation until done (or until now). */
  lead_seconds: number;
};
