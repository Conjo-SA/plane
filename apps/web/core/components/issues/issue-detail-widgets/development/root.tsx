/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { Check, Copy, GitBranch, Terminal } from "lucide-react";
import useSWR from "swr";
// plane imports
import { GitHubIntegrationService } from "@plane/services";
import type { TDevelopmentLink, TIssueDevelopment } from "@plane/types";
import { Collapsible, CollapsibleButton } from "@plane/ui";
import { cn } from "@plane/utils";
// local imports
import { useCopyText } from "@/components/settings/project/content/use-copy-text";
import { PR_STATES, prStateMeta, relativeTime } from "./pr-state";
import type { TPullRequestState } from "./pr-state";

const githubIntegrationService = new GitHubIntegrationService();

/** Commits shown before "Ver mais". */
const COMMITS_PREVIEW = 3;

type Props = {
  workspaceSlug: string;
  projectId: string;
  issueId: string;
};

/** Jira-like "Desenvolvimento" panel: summary, pull requests, branches and commits that mention the work item. */
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
  const total = data.pull_requests.length + data.branches.length + data.commits.length;
  return (
    <div className="flex flex-col gap-4 py-2">
      <CreateBranch branchName={data.branch_name} />
      {total === 0 ? (
        <p className="rounded-md border border-dashed border-subtle px-4 py-3 text-13 text-tertiary">
          Nenhuma branch, commit ou pull request ainda. Use a chave da tarefa no nome da branch, na mensagem do commit
          ou no título do PR para vincular aqui.
        </p>
      ) : (
        <>
          <Summary data={data} />
          {data.pull_requests.length > 0 && (
            <Section title="Pull requests">
              <div className="flex flex-col gap-2">
                {data.pull_requests.map((link) => (
                  <PullRequestCard key={link.id} link={link} />
                ))}
              </div>
            </Section>
          )}
          {data.branches.length > 0 && (
            <Section title="Branches">
              <ListBox>
                {data.branches.map((link) => (
                  <BranchRow key={link.id} link={link} />
                ))}
              </ListBox>
            </Section>
          )}
          {data.commits.length > 0 && <Commits commits={data.commits} />}
        </>
      )}
    </div>
  );
}

function summarizePullRequests(links: TDevelopmentLink[]): { text: string; state: TPullRequestState | null } {
  if (links.length === 0) return { text: "Nenhum", state: null };
  const counts = new Map<TPullRequestState, number>();
  for (const link of links) {
    const state = (link.state as TPullRequestState) || "open";
    counts.set(state, (counts.get(state) ?? 0) + 1);
  }
  const order: TPullRequestState[] = ["open", "draft", "merged", "closed"];
  const main = order.find((state) => counts.has(state)) ?? "open";
  const count = counts.get(main) ?? 0;
  const [one, many] = PR_STATES[main].plural;
  const extra = links.length - count;
  return { text: `${count} ${count === 1 ? one : many}${extra > 0 ? ` +${extra}` : ""}`, state: main };
}

function Summary({ data }: { data: TIssueDevelopment }) {
  const prs = summarizePullRequests(data.pull_requests);
  const prMeta = prs.state ? PR_STATES[prs.state] : null;
  const lastCommit = data.commits[0]?.event_at;
  return (
    <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
      <SummaryCell label="Pull request">
        <span className={cn("flex items-center gap-1.5", prMeta?.text)}>
          {prMeta && <prMeta.Icon className="size-4 flex-shrink-0" />}
          {prs.text}
        </span>
      </SummaryCell>
      <SummaryCell label="Branches">{data.branches.length}</SummaryCell>
      <SummaryCell label="Commits">
        <span>
          {data.commits.length}
          {lastCommit && (
            <span className="font-normal text-13 text-tertiary"> · último {relativeTime(lastCommit)}</span>
          )}
        </span>
      </SummaryCell>
    </div>
  );
}

function SummaryCell({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1 rounded-md border border-subtle px-3 py-2.5">
      <span className="text-11 text-tertiary">{label}</span>
      <span className="text-14 font-semibold text-primary">{children}</span>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-2">
      <h5 className="text-11 font-semibold tracking-wide text-tertiary uppercase">{title}</h5>
      {children}
    </div>
  );
}

function ListBox({ children }: { children: React.ReactNode }) {
  return <div className="flex flex-col divide-y divide-subtle rounded-md border border-subtle">{children}</div>;
}

function Avatar({ link }: { link: TDevelopmentLink }) {
  const who = link.author_login || link.author_name || "?";
  if (link.author_avatar_url)
    return <img src={link.author_avatar_url} alt="" className="size-5 flex-shrink-0 rounded-full" loading="lazy" />;
  return (
    <span className="flex size-5 flex-shrink-0 items-center justify-center rounded-full bg-layer-3 text-11 font-medium text-secondary">
      {who.charAt(0).toUpperCase()}
    </span>
  );
}

const repoName = (repository: string) => repository.split("/").pop() ?? repository;

function PullRequestCard({ link }: { link: TDevelopmentLink }) {
  const meta = prStateMeta(link.state);
  const head = link.metadata?.head;
  const base = link.metadata?.base;
  return (
    <a
      href={link.url}
      target="_blank"
      rel="noopener noreferrer"
      className="flex items-start gap-3 rounded-md border border-subtle px-3.5 py-3 hover:bg-layer-1"
    >
      <meta.Icon className={cn("mt-0.5 size-4 flex-shrink-0", meta.text)} />
      <div className="flex min-w-0 flex-grow flex-col gap-1.5">
        <div className="flex min-w-0 items-center gap-2">
          <span className="truncate text-13 font-semibold text-primary">{link.title}</span>
          <span className={cn("flex-shrink-0 rounded-full px-2 py-0.5 text-11 font-medium", meta.pill)}>
            {meta.label}
          </span>
        </div>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-11 text-tertiary">
          <span>
            #{link.external_id} · {repoName(link.repository)}
          </span>
          {head && base && (
            <span className="font-mono rounded-sm bg-layer-2 px-1.5 py-0.5 text-secondary">
              {head} → {base}
            </span>
          )}
          <span className="flex items-center gap-1.5">
            <Avatar link={link} />
            {[link.author_login || link.author_name, relativeTime(link.event_at)].filter(Boolean).join(" · ")}
          </span>
        </div>
      </div>
    </a>
  );
}

function BranchRow({ link }: { link: TDevelopmentLink }) {
  const deleted = link.state === "deleted";
  return (
    <a
      href={link.url}
      target="_blank"
      rel="noopener noreferrer"
      className="flex items-center gap-2.5 px-3.5 py-2.5 hover:bg-layer-1"
    >
      <GitBranch className={cn("size-3.5 flex-shrink-0", deleted ? "text-placeholder" : "text-secondary")} />
      <span
        className={cn(
          "font-mono min-w-0 flex-grow truncate text-13",
          deleted ? "text-tertiary line-through" : "text-primary"
        )}
      >
        {link.title}
      </span>
      <span className="hidden flex-shrink-0 text-11 text-tertiary sm:inline">{repoName(link.repository)}</span>
      <span
        className={cn(
          "flex-shrink-0 rounded-full px-2 py-0.5 text-11",
          deleted ? "bg-layer-2 text-secondary" : "bg-success-subtle text-success-primary"
        )}
      >
        {deleted ? "excluída" : "ativa"}
      </span>
    </a>
  );
}

function Commits({ commits }: { commits: TDevelopmentLink[] }) {
  const [showAll, setShowAll] = useState(false);
  const visible = showAll ? commits : commits.slice(0, COMMITS_PREVIEW);
  const hidden = commits.length - visible.length;
  return (
    <Section title="Commits">
      <ListBox>
        {visible.map((link) => (
          <a
            key={link.id}
            href={link.url}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-2.5 px-3.5 py-2.5 hover:bg-layer-1"
          >
            <Avatar link={link} />
            <span className="min-w-0 flex-grow truncate text-13 text-primary">{link.title}</span>
            <span className="font-mono flex-shrink-0 text-11 text-secondary">{link.external_id.slice(0, 7)}</span>
            <span className="hidden w-20 flex-shrink-0 text-right text-11 text-tertiary sm:inline">
              {relativeTime(link.event_at)}
            </span>
          </a>
        ))}
      </ListBox>
      {(hidden > 0 || showAll) && commits.length > COMMITS_PREVIEW && (
        <button
          type="button"
          className="self-start text-13 text-secondary hover:text-primary hover:underline"
          onClick={() => setShowAll((all) => !all)}
        >
          {showAll ? "Mostrar menos" : `Ver mais ${hidden} ${hidden === 1 ? "commit" : "commits"}`}
        </button>
      )}
    </Section>
  );
}

function CreateBranch({ branchName }: { branchName: string }) {
  const [isOpen, setIsOpen] = useState(false);
  const name = useCopyText();
  const command = useCopyText();
  return (
    <div className="flex flex-col gap-2">
      <button
        type="button"
        onClick={() => setIsOpen((open) => !open)}
        aria-expanded={isOpen}
        className="flex items-center gap-1.5 self-start rounded-md border border-subtle px-2.5 py-1.5 text-13 text-secondary hover:bg-layer-1 hover:text-primary"
      >
        <GitBranch className="size-3.5" />
        Criar branch
      </button>
      {isOpen && (
        <div className="flex flex-wrap items-center gap-2 rounded-md bg-layer-1 px-3 py-2">
          <code className="min-w-0 flex-grow truncate text-13 text-primary">{branchName}</code>
          <button
            type="button"
            className="flex items-center gap-1 rounded-sm px-1.5 py-1 text-11 text-secondary hover:bg-layer-2 hover:text-primary"
            onClick={() => void name.copy(branchName)}
          >
            {name.copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
            Copiar nome
          </button>
          <button
            type="button"
            className="flex items-center gap-1 rounded-sm px-1.5 py-1 text-11 text-secondary hover:bg-layer-2 hover:text-primary"
            onClick={() => void command.copy(`git checkout -b ${branchName}`)}
          >
            {command.copied ? <Check className="size-3.5" /> : <Terminal className="size-3.5" />}
            Copiar git checkout
          </button>
        </div>
      )}
    </div>
  );
}
