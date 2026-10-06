/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { observer } from "mobx-react";
import { Clock, Pencil, Trash2 } from "lucide-react";
import { Link } from "react-router";
import useSWR from "swr";
// plane imports
import { EUserPermissions, EUserPermissionsLevel } from "@plane/constants";
import { Button } from "@plane/propel/button";
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import { ConjoBillingService } from "@plane/services";
import type { TIssueTime, TIssueWorkLog, TWorkKind } from "@plane/types";
import { AlertModalCore, Collapsible, CollapsibleButton, Input } from "@plane/ui";
import { cn, getFileURL } from "@plane/utils";
// hooks
import { useUser, useUserPermissions } from "@/hooks/store/user";
// local imports
import { formatDayMonth, formatHours, formatMinutes, hoursToMinutes, todayISO } from "./format";

const billingService = new ConjoBillingService();

const WORK_KINDS: { value: TWorkKind; label: string }[] = [
  { value: "evolution", label: "Evolução" },
  { value: "maintenance", label: "Manutenção" },
  { value: "internal", label: "Interno" },
];

const BUDGET_STATUS: Record<NonNullable<TIssueTime["budget"]>["status"], { label: string; pill: string }> = {
  PENDING: { label: "Pendente", pill: "bg-warning-subtle text-warning-primary" },
  APPROVED: { label: "Aprovado", pill: "bg-success-subtle text-success-primary" },
  REJECTED: { label: "Recusado", pill: "bg-danger-subtle text-danger-primary" },
};

const readError = (err: unknown, fallback: string): string =>
  (err as { data?: { error?: string } } | undefined)?.data?.error || fallback;

const toastError = (err: unknown, fallback: string) =>
  setToast({ type: TOAST_TYPE.ERROR, title: "Erro", message: readError(err, fallback) });

type Props = {
  workspaceSlug: string;
  projectId: string;
  issueId: string;
  disabled: boolean;
};

/** "Tempo gasto" panel: time logged on the work item against its approved estimate, and the work kind. */
export function IssueTimeCollapsible(props: Props) {
  const { workspaceSlug, projectId, issueId, disabled } = props;
  const [isOpen, setIsOpen] = useState(true);
  const { data, mutate } = useSWR(
    workspaceSlug && projectId && issueId ? `ISSUE_TIME_${issueId}` : null,
    () => billingService.getIssueTime(workspaceSlug, projectId, issueId),
    { revalidateOnFocus: true }
  );

  if (!data) return null;
  const budgetMinutes = data.budget ? hoursToMinutes(data.budget.hours) : 0;

  return (
    <Collapsible
      isOpen={isOpen}
      onToggle={() => setIsOpen((open) => !open)}
      title={
        <CollapsibleButton
          isOpen={isOpen}
          title={
            <span className="flex items-center gap-2">
              <Clock className="size-4 text-secondary" />
              Tempo gasto
            </span>
          }
          indicatorElement={
            <span className="text-13 text-tertiary">
              <span className="font-semibold text-primary">{formatMinutes(data.total_minutes)}</span>
              {budgetMinutes > 0 && ` de ${formatMinutes(budgetMinutes)} orçadas`}
            </span>
          }
        />
      }
      buttonClassName="w-full"
    >
      <TimeContent
        workspaceSlug={workspaceSlug}
        projectId={projectId}
        issueId={issueId}
        disabled={disabled}
        data={data}
        onChange={(next) => void mutate(next, { revalidate: false })}
      />
    </Collapsible>
  );
}

type ContentProps = Props & { data: TIssueTime; onChange: (data: TIssueTime) => void };

function TimeContent(props: ContentProps) {
  const { data } = props;
  const budgetMinutes = data.budget ? hoursToMinutes(data.budget.hours) : 0;
  return (
    <div className="flex flex-col gap-4 py-3">
      {budgetMinutes > 0 && <Progress total={data.total_minutes} budget={budgetMinutes} />}
      <WorkKindChips {...props} />
      <BudgetBox {...props} />
      {!props.disabled && <LogForm {...props} />}
      <EntryList {...props} />
    </div>
  );
}

function Progress({ total, budget }: { total: number; budget: number }) {
  const over = total - budget;
  const percent = Math.min(100, Math.round((total / budget) * 100));
  return (
    <div className="flex flex-col gap-1.5">
      <div className="h-2 overflow-hidden rounded-full bg-layer-3">
        <span
          className={cn("block h-2 rounded-full", over > 0 ? "bg-warning-primary" : "bg-accent-primary")}
          style={{ width: `${percent}%` }}
        />
      </div>
      {over > 0 ? (
        <span className="text-12 font-medium text-warning-primary">+{formatMinutes(over)} acima do orçado</span>
      ) : (
        <span className="text-12 text-tertiary">
          {over === 0 ? "No limite do orçado" : `${formatMinutes(-over)} restantes no orçado`}
        </span>
      )}
    </div>
  );
}

function WorkKindChips(props: ContentProps) {
  const { workspaceSlug, projectId, issueId, disabled, data, onChange } = props;
  const [saving, setSaving] = useState<TWorkKind | null>(null);

  const handleSelect = async (kind: TWorkKind) => {
    if (disabled || saving || kind === data.kind) return;
    setSaving(kind);
    try {
      onChange(await billingService.setWorkKind(workspaceSlug, projectId, issueId, kind));
    } catch (err) {
      toastError(err, "Não foi possível alterar o tipo.");
    } finally {
      setSaving(null);
    }
  };

  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="w-14 text-13 text-tertiary">Tipo</span>
      {WORK_KINDS.map(({ value, label }) => {
        const selected = data.kind === value;
        return (
          <button
            key={value}
            type="button"
            disabled={disabled || saving !== null}
            aria-pressed={selected}
            onClick={() => void handleSelect(value)}
            className={cn(
              "rounded-full border px-3 py-1 text-13 transition-colors disabled:cursor-not-allowed",
              selected
                ? "border-transparent bg-accent-primary text-on-color"
                : "border-strong bg-layer-2 text-secondary enabled:hover:bg-layer-2-hover enabled:hover:text-primary",
              saving === value && "opacity-60"
            )}
          >
            {label}
          </button>
        );
      })}
    </div>
  );
}

function BudgetBox(props: ContentProps) {
  const { workspaceSlug, data } = props;
  const { budget, client, kind } = data;
  const noDebit = kind === "maintenance" || kind === "internal";
  const clientLink = client ? (
    <Link to={`/${workspaceSlug}/clients/${client.id}`} className="font-medium text-primary hover:underline">
      {client.name}
    </Link>
  ) : null;

  if (noDebit)
    return (
      <div className="flex flex-col gap-1 rounded-md border border-dashed border-strong px-3.5 py-3 text-13 text-secondary">
        <span>
          {kind === "maintenance" ? "Manutenção" : "Interno"} não desconta do pacote
          {clientLink && <> de {clientLink}</>}. O tempo gasto aparece só nos relatórios.
        </span>
      </div>
    );

  if (!budget)
    return (
      <div className="flex flex-col gap-1 rounded-md bg-layer-1 px-3.5 py-3 text-13 text-secondary">
        <span className="font-semibold text-primary">Orçamento</span>
        <span>Sem orçamento enviado para esta tarefa.</span>
        {clientLink && <span>Cliente: {clientLink}</span>}
      </div>
    );

  const status = BUDGET_STATUS[budget.status];
  const debited = data.debited_hours && hoursToMinutes(data.debited_hours) > 0 ? data.debited_hours : null;
  const deviation = data.total_minutes - hoursToMinutes(budget.hours);

  return (
    <div className="flex flex-col gap-2.5 rounded-md bg-layer-1 px-3.5 py-3 text-13 text-secondary">
      <span className="font-semibold text-primary">Orçamento</span>
      <span className="flex items-center justify-between gap-2">
        <span>Horas orçadas</span>
        <span className="font-semibold text-primary">{formatHours(budget.hours)}</span>
      </span>
      <span className="flex items-center justify-between gap-2">
        <span>Status</span>
        <span className={cn("rounded-full px-2 py-0.5 text-11 font-semibold", status.pill)}>{status.label}</span>
      </span>
      {(budget.status === "APPROVED" || debited || client) && (
        <span className="text-12 text-tertiary">
          {budget.status === "APPROVED" && budget.approved_by_email && (
            <>
              aprovado por {budget.approved_by_email}
              {budget.approved_at && ` em ${formatDayMonth(budget.approved_at)}`}
            </>
          )}
          {budget.status === "APPROVED" && budget.approved_by_email && (debited || client) && " · "}
          {debited ? (
            <>
              {formatHours(debited)} debitadas do pacote{clientLink ? <> de {clientLink}</> : null}
            </>
          ) : (
            clientLink && <>Cliente: {clientLink}</>
          )}
        </span>
      )}
      {budget.status === "APPROVED" && (
        <span className="flex items-center justify-between gap-2 border-t border-subtle pt-2.5">
          <span>Desvio até agora</span>
          <span className={cn(deviation > 0 ? "font-medium text-warning-primary" : "text-primary")}>
            {deviation > 0
              ? `+${formatMinutes(deviation)} acima do orçado`
              : `${formatMinutes(deviation)} (dentro do orçado)`}
          </span>
        </span>
      )}
    </div>
  );
}

function LogForm(props: ContentProps) {
  const { workspaceSlug, projectId, issueId, onChange } = props;
  const [duration, setDuration] = useState("");
  const [date, setDate] = useState(todayISO);
  const [description, setDescription] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!duration.trim() || submitting) return;
    setSubmitting(true);
    try {
      const next = await billingService.logIssueTime(workspaceSlug, projectId, issueId, {
        duration: duration.trim(),
        logged_on: date || undefined,
        description: description.trim() || undefined,
      });
      onChange(next);
      setDuration("");
      setDescription("");
    } catch (err) {
      toastError(err, "Não foi possível registrar o tempo.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form
      onSubmit={(event) => void handleSubmit(event)}
      className="grid grid-cols-2 items-end gap-2 sm:grid-cols-[96px_150px_minmax(0,1fr)_auto]"
    >
      <Field label="Duração">
        <Input
          value={duration}
          onChange={(e) => setDuration(e.target.value)}
          placeholder="1h30"
          className="w-full"
          aria-label="Duração"
        />
      </Field>
      <Field label="Data">
        <Input
          type="date"
          value={date}
          max={todayISO()}
          onChange={(e) => setDate(e.target.value)}
          className="w-full"
          aria-label="Data"
        />
      </Field>
      <Field label="O que foi feito (opcional)" className="col-span-2 sm:col-span-1">
        <Input
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="ex.: ajustes no filtro"
          className="w-full"
          aria-label="O que foi feito"
        />
      </Field>
      <Button
        type="submit"
        size="xl"
        className="col-span-2 sm:col-span-1"
        loading={submitting}
        disabled={!duration.trim()}
      >
        Adicionar
      </Button>
    </form>
  );
}

function Field({ label, className, children }: { label: string; className?: string; children: React.ReactNode }) {
  return (
    <label className={cn("flex min-w-0 flex-col gap-1 text-11 text-tertiary", className)}>
      {label}
      {children}
    </label>
  );
}

const EntryList = observer(function EntryList(props: ContentProps) {
  const { workspaceSlug, projectId, issueId, disabled, data, onChange } = props;
  const { data: currentUser } = useUser();
  const { allowPermissions } = useUserPermissions();
  const isAdmin = allowPermissions([EUserPermissions.ADMIN], EUserPermissionsLevel.PROJECT, workspaceSlug, projectId);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<TIssueWorkLog | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);

  if (data.entries.length === 0)
    return (
      <p className="rounded-md border border-dashed border-subtle px-4 py-3 text-13 text-tertiary">
        Nenhum tempo registrado ainda. Também é possível registrar pelo commit, com a chave da tarefa e #time 1h30.
      </p>
    );

  const handleDelete = async () => {
    if (!deleting) return;
    setIsDeleting(true);
    try {
      onChange(await billingService.deleteIssueTime(workspaceSlug, projectId, issueId, deleting.id));
      setDeleting(null);
    } catch (err) {
      toastError(err, "Não foi possível excluir o registro.");
    } finally {
      setIsDeleting(false);
    }
  };

  return (
    <>
      <div className="flex flex-col divide-y divide-subtle rounded-md border border-subtle">
        {data.entries.map((entry) => {
          const canManage = !disabled && (isAdmin || (!!currentUser?.id && entry.member?.id === currentUser.id));
          return editingId === entry.id ? (
            <EditEntryRow
              key={entry.id}
              {...props}
              entry={entry}
              onDone={(next) => {
                if (next) onChange(next);
                setEditingId(null);
              }}
            />
          ) : (
            <EntryRow
              key={entry.id}
              entry={entry}
              canManage={canManage}
              onEdit={() => setEditingId(entry.id)}
              onDelete={() => setDeleting(entry)}
            />
          );
        })}
      </div>
      <AlertModalCore
        isOpen={!!deleting}
        isSubmitting={isDeleting}
        handleClose={() => !isDeleting && setDeleting(null)}
        handleSubmit={() => void handleDelete()}
        title="Excluir registro de tempo"
        primaryButtonText={{ loading: "Excluindo", default: "Excluir" }}
        secondaryButtonText="Cancelar"
        content={
          deleting ? (
            <>
              Excluir o registro de <span className="font-medium text-primary">{formatMinutes(deleting.minutes)}</span>{" "}
              de {formatDayMonth(deleting.logged_on)}? Esta ação não pode ser desfeita.
            </>
          ) : null
        }
      />
    </>
  );
});

function MemberAvatar({ entry }: { entry: TIssueWorkLog }) {
  const src = entry.member?.avatar_url ? getFileURL(entry.member.avatar_url) : undefined;
  if (src) return <img src={src} alt="" className="size-6 flex-shrink-0 rounded-full object-cover" loading="lazy" />;
  const initial = (entry.member?.display_name || "?").charAt(0).toUpperCase();
  return (
    <span className="flex size-6 flex-shrink-0 items-center justify-center rounded-full bg-layer-3 text-11 font-medium text-secondary">
      {initial}
    </span>
  );
}

function entryDescription(entry: TIssueWorkLog): { text: string; muted: boolean } {
  if (entry.description) {
    if (entry.source === "commit") return { text: `via commit · ${entry.description}`, muted: true };
    return { text: entry.description, muted: false };
  }
  if (entry.source === "commit") return { text: "via commit", muted: true };
  if (entry.source === "chat") return { text: "via chat", muted: true };
  return { text: "Sem descrição", muted: true };
}

type EntryRowProps = { entry: TIssueWorkLog; canManage: boolean; onEdit: () => void; onDelete: () => void };

function EntryRow({ entry, canManage, onEdit, onDelete }: EntryRowProps) {
  const description = entryDescription(entry);
  const meta = [formatDayMonth(entry.logged_on), entry.member?.display_name].filter(Boolean).join(" · ");
  return (
    <div className="group flex items-center gap-3 px-3.5 py-2.5">
      <MemberAvatar entry={entry} />
      <div className="flex min-w-0 flex-grow flex-col">
        <span className={cn("truncate text-13", description.muted ? "text-tertiary" : "text-primary")}>
          {description.text}
        </span>
        <span className="text-11 text-tertiary">{meta}</span>
      </div>
      {canManage && (
        <div className="flex flex-shrink-0 items-center gap-0.5 opacity-100 transition-opacity sm:opacity-0 sm:group-focus-within:opacity-100 sm:group-hover:opacity-100">
          <button
            type="button"
            onClick={onEdit}
            aria-label="Editar registro"
            className="rounded-sm p-1 text-tertiary hover:bg-layer-2 hover:text-primary"
          >
            <Pencil className="size-3.5" />
          </button>
          <button
            type="button"
            onClick={onDelete}
            aria-label="Excluir registro"
            className="rounded-sm p-1 text-tertiary hover:bg-layer-2 hover:text-danger-primary"
          >
            <Trash2 className="size-3.5" />
          </button>
        </div>
      )}
      <span className="font-mono w-14 flex-shrink-0 text-right text-13 text-primary">
        {formatMinutes(entry.minutes)}
      </span>
    </div>
  );
}

type EditEntryRowProps = ContentProps & { entry: TIssueWorkLog; onDone: (next: TIssueTime | null) => void };

function EditEntryRow(props: EditEntryRowProps) {
  const { workspaceSlug, projectId, issueId, entry, onDone } = props;
  const [duration, setDuration] = useState(formatMinutes(entry.minutes));
  const [date, setDate] = useState(entry.logged_on);
  const [description, setDescription] = useState(entry.description);
  const [saving, setSaving] = useState(false);

  const handleSave = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!duration.trim() || saving) return;
    setSaving(true);
    try {
      onDone(
        await billingService.updateIssueTime(workspaceSlug, projectId, issueId, entry.id, {
          duration: duration.trim(),
          logged_on: date,
          description: description.trim(),
        })
      );
    } catch (err) {
      toastError(err, "Não foi possível salvar o registro.");
      setSaving(false);
    }
  };

  return (
    <form
      onSubmit={(event) => void handleSave(event)}
      className="grid grid-cols-2 items-center gap-2 bg-layer-1 px-3.5 py-2.5 sm:grid-cols-[88px_150px_minmax(0,1fr)_auto]"
    >
      <Input
        value={duration}
        onChange={(e) => setDuration(e.target.value)}
        placeholder="1h30"
        aria-label="Duração"
        className="w-full"
      />
      <Input
        type="date"
        value={date}
        max={todayISO()}
        onChange={(e) => setDate(e.target.value)}
        aria-label="Data"
        className="w-full"
      />
      <Input
        value={description}
        onChange={(e) => setDescription(e.target.value)}
        placeholder="O que foi feito"
        aria-label="O que foi feito"
        className="col-span-2 w-full sm:col-span-1"
      />
      <div className="col-span-2 flex items-center justify-end gap-1.5 sm:col-span-1">
        <Button type="button" variant="secondary" size="lg" disabled={saving} onClick={() => onDone(null)}>
          Cancelar
        </Button>
        <Button type="submit" size="lg" loading={saving} disabled={!duration.trim()}>
          Salvar
        </Button>
      </div>
    </form>
  );
}
