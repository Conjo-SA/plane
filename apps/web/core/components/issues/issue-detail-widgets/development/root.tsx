/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import {
  Check,
  Copy,
  GitBranch,
  GitCommitHorizontal,
  GitMerge,
  GitPullRequest,
  GitPullRequestClosed,
  GitPullRequestDraft,
  Terminal,
} from "lucide-react";
import useSWR from "swr";
// plane imports
import { GitHubIntegrationService } from "@plane/services";
import type { TDevelopmentLink, TIssueDevelopment } from "@plane/types";
import { Collapsible, CollapsibleButton } from "@plane/ui";
import { cn } from "@plane/utils";
// local imports
import { useCopyText } from "@/components/settings/project/content/use-copy-text";

const githubIntegrationService = new GitHubIntegrationService();

type Props = {
  workspaceSlug: string;
  projectId: string;
  issueId: string;
};

const PR_STATE: Record<string, { label: string; className: string; Icon: typeof GitPullRequest }> = {
  open: { label: "Aberto", className: "text-success-primary", Icon: GitPullRequest },
  draft: { label: "Rascunho", className: "text-tertiary", Icon: GitPullRequestDraft },
  merged: { label: "Mergeado", className: "text-accent-primary", Icon: GitMerge },
  closed: { label: "Fechado", className: "text-danger-primary", Icon: GitPullRequestClosed },
};

const relativeTime = (value: string | null) => {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const seconds = Math.round((date.getTime() - Date.now()) / 1000);
  const units: [Intl.RelativeTimeFormatUnit, number][] = [
    ["year", 31536000],
    ["month", 2592000],
    ["day", 86400],
    ["hour", 3600],
    ["minute", 60],
  ];
  const format = new Intl.RelativeTimeFormat("pt-BR", { numeric: "auto" });
  for (const [unit, size] of units) {
    if (Math.abs(seconds) >= size) return format.format(Math.round(seconds / size), unit);
  }
  return "agora";
};

/** Jira-like "Desenvolvimento" panel: branches, commits and pull requests that mention the work item. */
export function IssueDevelopmentCollapsible(props: Props) {
  const { workspaceSlug, projectId, issueId } = props;
  const [isOpen, setIsOpen] = useState(true);
  const { data } = useSWR(
    workspaceSlug && projectId && issueId ? `ISSUE_DEVELOPMENT_${issueId}` : null,
    () => githubIntegrationService.retrieveIssueDevelopment(workspaceSlug, projectId, issueId),
    { revalidateOnFocus: true }
  );

  if (!data) return null;
  const total = data.pull_requests.length + data.branches.length + data.commits.length;
  if (!data.github_configured && total === 0) return null;

  return (
    <Collapsible
      isOpen={isOpen}
      onToggle={() => setIsOpen((open) => !open)}
      title={
        <CollapsibleButton
          isOpen={isOpen}
          title="Desenvolvimento"
          indicatorElement={
            <span className="flex items-center justify-center">
              <p className="text-14 !leading-3 text-tertiary">{total}</p>
            </span>
          }
        />
      }
      buttonClassName="w-full"
    >
      <DevelopmentContent data={data} />
    </Collapsible>
  );
}

function DevelopmentContent({ data }: { data: TIssueDevelopment }) {
  return (
    <div className="flex flex-col gap-4 py-2">
      <CreateBranch branchName={data.branch_name} />
      {data.pull_requests.length > 0 && (
        <Section title="Pull requests">
          {data.pull_requests.map((link) => (
            <PullRequestRow key={link.id} link={link} />
          ))}
        </Section>
      )}
      {data.branches.length > 0 && (
        <Section title="Branches">
          {data.branches.map((link) => (
            <LinkRow
              key={link.id}
              link={link}
              icon={<GitBranch className="size-3.5 shrink-0 text-tertiary" />}
              label={<span className={cn("truncate", { "line-through": link.state === "deleted" })}>{link.title}</span>}
              suffix={link.state === "deleted" ? "excluída" : undefined}
            />
          ))}
        </Section>
      )}
      {data.commits.length > 0 && (
        <Section title="Commits">
          {data.commits.map((link) => (
            <LinkRow
              key={link.id}
              link={link}
              icon={<GitCommitHorizontal className="size-3.5 shrink-0 text-tertiary" />}
              label={
                <span className="flex min-w-0 items-center gap-2">
                  <code className="shrink-0 text-11 text-tertiary">{link.external_id.slice(0, 7)}</code>
                  <span className="truncate">{link.title}</span>
                </span>
              }
            />
          ))}
        </Section>
      )}
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <h5 className="text-12 font-medium text-tertiary">{title}</h5>
      <div className="flex flex-col">{children}</div>
    </div>
  );
}

function LinkRow(props: { link: TDevelopmentLink; icon: React.ReactNode; label: React.ReactNode; suffix?: string }) {
  const { link, icon, label, suffix } = props;
  const who = link.author_name || link.author_login;
  return (
    <a
      href={link.url}
      target="_blank"
      rel="noopener noreferrer"
      className="group flex items-center gap-2 rounded-sm px-2 py-1.5 text-13 text-secondary hover:bg-layer-1"
    >
      {icon}
      <span className="min-w-0 flex-grow">{label}</span>
      <span className="hidden shrink-0 text-11 text-tertiary sm:inline">
        {[suffix, link.repository, who, relativeTime(link.event_at)].filter(Boolean).join(" · ")}
      </span>
    </a>
  );
}

function PullRequestRow({ link }: { link: TDevelopmentLink }) {
  const state = PR_STATE[link.state] ?? PR_STATE.open;
  return (
    <LinkRow
      link={link}
      icon={<state.Icon className={cn("size-3.5 shrink-0", state.className)} />}
      label={
        <span className="flex min-w-0 items-center gap-2">
          <span className="shrink-0 text-tertiary">#{link.external_id}</span>
          <span className="truncate">{link.title}</span>
          <span className={cn("shrink-0 rounded-sm border border-subtle px-1.5 text-11", state.className)}>
            {state.label}
          </span>
        </span>
      }
    />
  );
}

function CreateBranch({ branchName }: { branchName: string }) {
  const name = useCopyText();
  const command = useCopyText();
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-sm border border-subtle px-2 py-1.5">
      <GitBranch className="size-3.5 shrink-0 text-tertiary" />
      <span className="text-12 text-tertiary">Criar branch</span>
      <code className="min-w-0 flex-grow truncate text-12 text-secondary">{branchName}</code>
      <button
        type="button"
        className="rounded-sm p-1 text-tertiary hover:bg-layer-1 hover:text-primary"
        onClick={() => void name.copy(branchName)}
        aria-label="Copiar nome da branch"
        title="Copiar nome da branch"
      >
        {name.copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
      </button>
      <button
        type="button"
        className="rounded-sm p-1 text-tertiary hover:bg-layer-1 hover:text-primary"
        onClick={() => void command.copy(`git checkout -b ${branchName}`)}
        aria-label="Copiar comando git"
        title="Copiar git checkout -b"
      >
        {command.copied ? <Check className="size-3.5" /> : <Terminal className="size-3.5" />}
      </button>
    </div>
  );
}
