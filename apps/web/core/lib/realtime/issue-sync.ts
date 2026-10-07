/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { chunk, clone } from "lodash-es";
import { runInAction } from "mobx";
import { mutate } from "swr";
import type { TIssue } from "@plane/types";
// components (SWR keys of the Conjo widgets)
import { getIssueClientSWRKey } from "@/components/issues/issue-detail/client/root";
import { getProjectClientSummarySWRKey } from "@/components/issues/issue-detail/client/card-chip";
import { getIssueTimeSWRKey } from "@/components/issues/issue-detail-widgets/time/root";
// lib
import { store } from "@/lib/store-context";
// services
import { IssueService } from "@/services/issue";
// store
import type { IBaseIssuesStore } from "@/store/issue/helpers/base-issues.store";
import { onBeforeBackgroundApply } from "@/store/issue/helpers/background-refresh";
// local
import type { TRealtimeEvent } from "./connection";
import { animateRemoval, captureLayout, isDragInProgress, playLayoutChanges } from "./motion";

const COALESCE_MS = 150;
const VIEW_REFRESH_DEBOUNCE_MS = 600;
const FETCH_CHUNK = 50;

type TPendingIssue = {
  types: Set<string>;
  fields: Set<string>;
  actorIds: Set<string>;
  remote: boolean;
};

type TPendingBatch = {
  workspaceSlug: string;
  issues: Map<string, TPendingIssue>;
};

const issueService = new IssueService();

/** Project-level issue stores that can be on screen for a project (board, list, spreadsheet, calendar, gantt). */
const projectIssueStores = (): IBaseIssuesStore[] => {
  const root = store.issue;
  return [root.projectIssues, root.cycleIssues, root.moduleIssues, root.projectViewIssues];
};

/** Work items open in a peek overview or on the work item page. */
const openIssueIds = (): Set<string> => {
  const ids = new Set<string>();
  const peekIssueId = store.issue.issueDetail.peekIssue?.issueId;
  if (peekIssueId) ids.add(peekIssueId);
  const workItem = store.router.query?.workItem?.toString();
  if (workItem) {
    const issueId = store.issue.issues.getIssueIdByIdentifier(workItem);
    if (issueId) ids.add(issueId);
  }
  return ids;
};

const isOwnEventInThisTab = (event: TRealtimeEvent) =>
  !!event.actor_id &&
  event.actor_id === store.user.data?.id &&
  typeof document !== "undefined" &&
  document.visibilityState === "visible" &&
  document.hasFocus();

const actorLabel = (actorIds: Set<string>) => {
  if (actorIds.size !== 1) return undefined;
  const [actorId] = [...actorIds];
  const member = store.memberRoot.getUserDetails(actorId);
  const name = member?.display_name || member?.first_name;
  return name ? `Atualizado por ${name}` : undefined;
};

/**
 * Applies realtime notifications to the MobX stores: coalesces bursts per work item, refetches
 * them through the authenticated REST API and updates the issue map and every list that holds
 * them, so cards move to the right column/position with the stores' own grouping and ordering.
 */
export class RealtimeIssueSync {
  private readonly pending = new Map<string, TPendingBatch>();
  private readonly timers = new Map<string, ReturnType<typeof setTimeout>>();
  private readonly viewRefreshTimers = new Map<string, ReturnType<typeof setTimeout>>();

  constructor() {
    // background view refreshes: measure the cards right before the lists are replaced, then let
    // them glide to their new places and fade the new ones in
    onBeforeBackgroundApply(() => {
      const snapshot = captureLayout();
      playLayoutChanges(snapshot, { changedIssueIds: new Set(snapshot.byIssue.keys()), animateNewCards: true });
    });
  }

  handleEvent = (event: TRealtimeEvent) => {
    if (!event?.project_id || !Array.isArray(event.issue_ids) || event.issue_ids.length === 0) return;
    const ownEvent = isOwnEventInThisTab(event);
    if (ownEvent) {
      // already applied optimistically here; only side effects computed by the server are refreshed
      this.revalidateWidgets(event, new Set(event.issue_ids));
      return;
    }

    const batch = this.pending.get(event.project_id) ?? {
      workspaceSlug: event.workspace_slug,
      issues: new Map<string, TPendingIssue>(),
    };
    for (const issueId of event.issue_ids) {
      const entry = batch.issues.get(issueId) ?? {
        types: new Set<string>(),
        fields: new Set<string>(),
        actorIds: new Set<string>(),
        remote: false,
      };
      entry.types.add(event.type);
      event.fields?.forEach((field) => entry.fields.add(field));
      if (event.actor_id) entry.actorIds.add(event.actor_id);
      entry.remote = entry.remote || event.actor_id !== store.user.data?.id;
      batch.issues.set(issueId, entry);
    }
    this.pending.set(event.project_id, batch);
    this.revalidateWidgets(event, new Set(event.issue_ids));

    if (!this.timers.has(event.project_id)) {
      this.timers.set(
        event.project_id,
        setTimeout(() => {
          this.timers.delete(event.project_id);
          void this.flush(event.project_id);
        }, COALESCE_MS)
      );
    }
  };

  /** After a reconnection: events may have been missed, refresh what is on screen. */
  resync = (workspaceSlug: string, projectId: string) => {
    this.scheduleViewRefresh(workspaceSlug, projectId, true);
    const openIds = openIssueIds();
    openIds.forEach((issueId) => {
      const issue = store.issue.issues.getIssueById(issueId);
      if (issue?.project_id !== projectId) return;
      void this.refreshDetail(
        workspaceSlug,
        projectId,
        issueId,
        new Set(["issue.updated", "comment.updated"]),
        new Set()
      );
    });
  };

  private async flush(projectId: string) {
    const batch = this.pending.get(projectId);
    if (!batch) return;
    if (isDragInProgress()) {
      // never move cards under the user's drag: try again once the drop happened
      this.timers.set(
        projectId,
        setTimeout(() => {
          this.timers.delete(projectId);
          void this.flush(projectId);
        }, 300)
      );
      return;
    }
    this.pending.delete(projectId);
    const { workspaceSlug } = batch;

    try {
      const deletedIds = new Set<string>();
      const fetchIds: string[] = [];
      batch.issues.forEach((entry, issueId) => {
        if (entry.types.has("issue.deleted")) deletedIds.add(issueId);
        else fetchIds.push(issueId);
      });

      // refetch through the API (permissions apply); missing = deleted, archived or no longer visible
      const fetched = new Map<string, TIssue>();
      const responses = await Promise.all(
        chunk(fetchIds, FETCH_CHUNK).map((ids) =>
          issueService.retrieveIssues(workspaceSlug, projectId, ids, { source: "realtime" })
        )
      );
      responses.flat().forEach((issue) => {
        if (issue?.id && issue.project_id === projectId) fetched.set(issue.id, issue);
      });
      fetchIds.filter((issueId) => !fetched.has(issueId)).forEach((issueId) => deletedIds.add(issueId));

      const stores = projectIssueStores();
      const removedFromLists = new Set(
        [...deletedIds].filter((issueId) => stores.some((s) => s.hasIssueInList(issueId)))
      );
      await animateRemoval(removedFromLists);

      const snapshot = captureLayout();
      const changedIds = new Set<string>();
      const unknownIds = new Set<string>();
      const touchedStores = new Set<IBaseIssuesStore>();

      runInAction(() => {
        fetched.forEach((issue, issueId) => {
          const before = clone(store.issue.issues.getIssueById(issueId));
          if (before) store.issue.issues.updateIssue(issueId, issue);
          else store.issue.issues.addIssue([issue]);
          const after = store.issue.issues.getIssueById(issueId);
          let inSomeList = false;
          for (const issueStore of stores) {
            if (!issueStore.hasIssueInList(issueId)) continue;
            inSomeList = true;
            touchedStores.add(issueStore);
            issueStore.updateIssueList(after, before);
          }
          if (inSomeList) changedIds.add(issueId);
          else unknownIds.add(issueId);
        });

        deletedIds.forEach((issueId) => {
          for (const issueStore of stores) {
            if (!issueStore.hasIssueInList(issueId)) continue;
            touchedStores.add(issueStore);
            issueStore.removeIssueFromList(issueId);
          }
          const isOpen = openIssueIds().has(issueId);
          if (batch.issues.get(issueId)?.types.has("issue.deleted") && !isOpen) store.issue.issues.removeIssue(issueId);
        });
      });

      const highlightIds = new Set([...changedIds].filter((issueId) => batch.issues.get(issueId)?.remote));
      const actorIds = new Set<string>();
      highlightIds.forEach((issueId) =>
        batch.issues.get(issueId)?.actorIds.forEach((actorId) => actorIds.add(actorId))
      );
      playLayoutChanges(snapshot, {
        changedIssueIds: changedIds,
        highlightIssueIds: highlightIds,
        badgeText: actorLabel(actorIds),
      });

      // cycle/module progress follows the items
      const { cycleId, moduleId } = store.router;
      if (cycleId && touchedStores.has(store.issue.cycleIssues)) {
        store.cycle.fetchCycleDetails(workspaceSlug, projectId, cycleId).catch(() => undefined);
      }
      if (moduleId && touchedStores.has(store.issue.moduleIssues)) {
        store.module.fetchModuleDetails(workspaceSlug, projectId, moduleId).catch(() => undefined);
      }

      // new items, or items that may now match the view's filters: refresh the view itself
      if (unknownIds.size > 0) this.scheduleViewRefresh(workspaceSlug, projectId, false);

      // open work item (peek or page)
      const openIds = openIssueIds();
      batch.issues.forEach((entry, issueId) => {
        if (openIds.has(issueId)) void this.refreshDetail(workspaceSlug, projectId, issueId, entry.types, entry.fields);
      });
      // a sub-item of the open work item changed (or was created)
      const parentIds = new Set<string>();
      fetched.forEach((issue) => {
        if (issue.parent_id && openIds.has(issue.parent_id)) parentIds.add(issue.parent_id);
      });
      parentIds.forEach((parentId) => {
        store.issue.issueDetail.fetchSubIssues(workspaceSlug, projectId, parentId).catch(() => undefined);
      });
    } catch {
      // realtime is best effort: a failed refresh never breaks the page
    }
  }

  private async refreshDetail(
    workspaceSlug: string,
    projectId: string,
    issueId: string,
    types: Set<string>,
    fields: Set<string>
  ) {
    const detail = store.issue.issueDetail;
    const has = (prefix: string) => [...types].some((type) => type.startsWith(prefix));
    const tasks: Promise<unknown>[] = [detail.fetchActivities(workspaceSlug, projectId, issueId, "mutate")];
    if (has("comment.") || has("comment_reaction."))
      tasks.push(detail.comment.syncComments(workspaceSlug, projectId, issueId));
    if (has("link.")) tasks.push(detail.fetchLinks(workspaceSlug, projectId, issueId));
    if (has("attachment.")) tasks.push(detail.fetchAttachments(workspaceSlug, projectId, issueId));
    if (has("issue_relation.")) tasks.push(detail.fetchRelations(workspaceSlug, projectId, issueId));
    if (has("issue_reaction.")) tasks.push(detail.fetchReactions(workspaceSlug, projectId, issueId));
    if (fields.has("parent") || fields.has("parent_id"))
      tasks.push(detail.fetchSubIssues(workspaceSlug, projectId, issueId));
    await Promise.allSettled(tasks);
  }

  /** Conjo widgets (time spent, client chip, development panel) live in SWR: revalidate their keys. */
  private revalidateWidgets(event: TRealtimeEvent, issueIds: Set<string>) {
    const fields = new Set(event.fields ?? []);
    const openIds = openIssueIds();
    const clientMayChange = event.type === "issue.client" || fields.has("labels") || fields.has("label_ids");
    issueIds.forEach((issueId) => {
      if (!openIds.has(issueId)) return;
      void mutate(getIssueTimeSWRKey(issueId));
      if (clientMayChange || event.type === "issue.work_kind") void mutate(getIssueClientSWRKey(issueId));
      if (event.type === "issue.development") void mutate(`ISSUE_DEVELOPMENT_${issueId}`);
    });
    if (clientMayChange || event.type === "issue.created") void mutate(getProjectClientSummarySWRKey(event.project_id));
    if (event.type === "issue.development") void mutate(`PROJECT_DEVELOPMENT_SUMMARY_${event.project_id}`);
  }

  /**
   * Refetches the first page of the view on screen without clearing it. Skipped when the user
   * loaded more pages (a refetch would drop them) unless forced after a reconnection.
   */
  private scheduleViewRefresh(workspaceSlug: string, projectId: string, force: boolean) {
    const existing = this.viewRefreshTimers.get(projectId);
    if (existing) clearTimeout(existing);
    this.viewRefreshTimers.set(
      projectId,
      setTimeout(() => {
        this.viewRefreshTimers.delete(projectId);
        if (isDragInProgress()) {
          this.scheduleViewRefresh(workspaceSlug, projectId, force);
          return;
        }
        void this.refreshView(workspaceSlug, projectId, force);
      }, VIEW_REFRESH_DEBOUNCE_MS)
    );
  }

  private async refreshView(workspaceSlug: string, projectId: string, force: boolean) {
    const { router } = store;
    if (router.projectId !== projectId || typeof window === "undefined") return;
    const path = window.location.pathname;
    const root = store.issue;
    try {
      if (router.viewId && path.includes("/views/")) {
        if (!force && root.projectViewIssues.hasLoadedBeyondFirstPage()) return;
        await root.projectViewIssues.fetchIssuesWithExistingPagination(
          workspaceSlug,
          projectId,
          router.viewId,
          "background"
        );
      } else if (router.cycleId && path.includes("/cycles/")) {
        if (!force && root.cycleIssues.hasLoadedBeyondFirstPage()) return;
        await root.cycleIssues.fetchIssuesWithExistingPagination(
          workspaceSlug,
          projectId,
          "background",
          router.cycleId
        );
      } else if (router.moduleId && path.includes("/modules/")) {
        if (!force && root.moduleIssues.hasLoadedBeyondFirstPage()) return;
        await root.moduleIssues.fetchIssuesWithExistingPagination(
          workspaceSlug,
          projectId,
          "background",
          router.moduleId
        );
      } else if (path.includes(`/projects/${projectId}/issues`)) {
        if (!force && root.projectIssues.hasLoadedBeyondFirstPage()) return;
        await root.projectIssues.fetchIssuesWithExistingPagination(workspaceSlug, projectId, "background");
      }
    } catch {
      // best effort
    }
  }
}

export const realtimeIssueSync = new RealtimeIssueSync();
