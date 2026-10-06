/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

// plane imports
import { API_BASE_URL } from "@plane/constants";
import type {
  TClient,
  TClientContact,
  TClientContactInput,
  TClientContract,
  TClientContractCreate,
  TClientCreate,
  TClientLedger,
  TClientListItem,
  TClientTimeline,
  TClientUpdate,
  TIssueTime,
  TIssueTimeCreate,
  TIssueTimeUpdate,
  TPackageSummary,
  TClientNoteCreate,
  TClientTimelineType,
  TWorkKind,
} from "@plane/types";
// api service
import { APIService } from "../api.service";

/**
 * Conjo: time spent on work items, clients, hour packages (statement) and the client timeline.
 * Errors are rethrown as the axios response, whose `data.error` carries a pt-BR message.
 * @extends {APIService}
 */
export class ConjoBillingService extends APIService {
  constructor(BASE_URL?: string) {
    super(BASE_URL || API_BASE_URL);
  }

  private async call<T>(promise: Promise<{ data: T }>): Promise<T> {
    return promise
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response;
      });
  }

  private issueUrl(workspaceSlug: string, projectId: string, issueId: string): string {
    return `/api/workspaces/${workspaceSlug}/projects/${projectId}/issues/${issueId}`;
  }

  private clientUrl(workspaceSlug: string, clientId: string): string {
    return `/api/workspaces/${workspaceSlug}/clients/${clientId}`;
  }

  // Time spent and work kind

  async getIssueTime(workspaceSlug: string, projectId: string, issueId: string): Promise<TIssueTime> {
    return this.call(this.get(`${this.issueUrl(workspaceSlug, projectId, issueId)}/time/`));
  }

  async logIssueTime(
    workspaceSlug: string,
    projectId: string,
    issueId: string,
    data: TIssueTimeCreate
  ): Promise<TIssueTime> {
    return this.call(this.post(`${this.issueUrl(workspaceSlug, projectId, issueId)}/time/`, data));
  }

  async updateIssueTime(
    workspaceSlug: string,
    projectId: string,
    issueId: string,
    entryId: string,
    data: TIssueTimeUpdate
  ): Promise<TIssueTime> {
    return this.call(this.patch(`${this.issueUrl(workspaceSlug, projectId, issueId)}/time/${entryId}/`, data));
  }

  async deleteIssueTime(
    workspaceSlug: string,
    projectId: string,
    issueId: string,
    entryId: string
  ): Promise<TIssueTime> {
    return this.call(this.delete(`${this.issueUrl(workspaceSlug, projectId, issueId)}/time/${entryId}/`));
  }

  async setWorkKind(workspaceSlug: string, projectId: string, issueId: string, kind: TWorkKind): Promise<TIssueTime> {
    return this.call(this.put(`${this.issueUrl(workspaceSlug, projectId, issueId)}/work-kind/`, { kind }));
  }

  // Clients

  async listClients(workspaceSlug: string): Promise<TClientListItem[]> {
    return this.call(this.get(`/api/workspaces/${workspaceSlug}/clients/`));
  }

  async createClient(workspaceSlug: string, data: TClientCreate): Promise<TClient> {
    return this.call(this.post(`/api/workspaces/${workspaceSlug}/clients/`, data));
  }

  async getClient(workspaceSlug: string, clientId: string): Promise<TClient> {
    return this.call(this.get(`${this.clientUrl(workspaceSlug, clientId)}/`));
  }

  async updateClient(workspaceSlug: string, clientId: string, data: TClientUpdate): Promise<TClient> {
    return this.call(this.patch(`${this.clientUrl(workspaceSlug, clientId)}/`, data));
  }

  async deleteClient(workspaceSlug: string, clientId: string): Promise<void> {
    return this.call(this.delete(`${this.clientUrl(workspaceSlug, clientId)}/`));
  }

  async addContact(workspaceSlug: string, clientId: string, data: TClientContactInput): Promise<TClientContact> {
    return this.call(this.post(`${this.clientUrl(workspaceSlug, clientId)}/contacts/`, data));
  }

  async updateContact(
    workspaceSlug: string,
    clientId: string,
    contactId: string,
    data: TClientContactInput
  ): Promise<TClientContact> {
    return this.call(this.patch(`${this.clientUrl(workspaceSlug, clientId)}/contacts/${contactId}/`, data));
  }

  async deleteContact(workspaceSlug: string, clientId: string, contactId: string): Promise<void> {
    return this.call(this.delete(`${this.clientUrl(workspaceSlug, clientId)}/contacts/${contactId}/`));
  }

  async setClientProjects(workspaceSlug: string, clientId: string, projectIds: string[]): Promise<TClient> {
    return this.call(this.put(`${this.clientUrl(workspaceSlug, clientId)}/projects/`, { project_ids: projectIds }));
  }

  async createContract(workspaceSlug: string, clientId: string, data: TClientContractCreate): Promise<TClientContract> {
    return this.call(this.post(`${this.clientUrl(workspaceSlug, clientId)}/contracts/`, data));
  }

  async updateContract(
    workspaceSlug: string,
    clientId: string,
    contractId: string,
    data: Partial<TClientContractCreate>
  ): Promise<TClientContract> {
    return this.call(this.patch(`${this.clientUrl(workspaceSlug, clientId)}/contracts/${contractId}/`, data));
  }

  // Statement

  async getLedger(
    workspaceSlug: string,
    clientId: string,
    params?: { from?: string; to?: string }
  ): Promise<TClientLedger> {
    return this.call(this.get(`${this.clientUrl(workspaceSlug, clientId)}/ledger/`, { params }));
  }

  async adjustLedger(workspaceSlug: string, clientId: string, hours: string, note: string): Promise<TPackageSummary> {
    return this.call(this.post(`${this.clientUrl(workspaceSlug, clientId)}/ledger/adjust/`, { hours, note }));
  }

  async reverseDebit(workspaceSlug: string, clientId: string, entryId: string, note: string): Promise<TPackageSummary> {
    return this.call(this.post(`${this.clientUrl(workspaceSlug, clientId)}/ledger/${entryId}/reverse/`, { note }));
  }

  /** URL of the CSV export (debits, reversals and excess hours of a period) for the finance system. */
  ledgerExportUrl(
    workspaceSlug: string,
    clientId: string,
    params: { from?: string; to?: string; mark_exported?: boolean }
  ): string {
    const query = new URLSearchParams();
    if (params.from) query.set("from", params.from);
    if (params.to) query.set("to", params.to);
    if (params.mark_exported) query.set("mark_exported", "1");
    return `${API_BASE_URL}${this.clientUrl(workspaceSlug, clientId)}/ledger/export/?${query.toString()}`;
  }

  // Timeline

  async getTimeline(
    workspaceSlug: string,
    clientId: string,
    params?: { types?: TClientTimelineType[]; before?: string; limit?: number }
  ): Promise<TClientTimeline> {
    return this.call(
      this.get(`${this.clientUrl(workspaceSlug, clientId)}/timeline/`, {
        params: {
          types: params?.types?.join(",") || undefined,
          before: params?.before,
          limit: params?.limit,
        },
      })
    );
  }

  async addTimelineNote(workspaceSlug: string, clientId: string, data: TClientNoteCreate): Promise<{ id: string }> {
    return this.call(this.post(`${this.clientUrl(workspaceSlug, clientId)}/timeline/notes/`, data));
  }

  async deleteTimelineNote(workspaceSlug: string, clientId: string, noteId: string): Promise<void> {
    return this.call(this.delete(`${this.clientUrl(workspaceSlug, clientId)}/timeline/notes/${noteId}/`));
  }
}
