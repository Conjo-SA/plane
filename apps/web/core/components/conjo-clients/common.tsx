/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { FormEvent, ReactNode } from "react";
import Link from "next/link";
// plane imports
import { EUserPermissions, EUserPermissionsLevel } from "@plane/constants";
import { Button } from "@plane/propel/button";
import { EModalPosition, EModalWidth, ModalCore } from "@plane/ui";
import { cn } from "@plane/utils";
// hooks
import { useUserPermissions } from "@/hooks/store/user";

/** Writes on clients (create, edit, contracts, adjustments, export, projects) are for workspace admins only. */
export const useIsClientsAdmin = (workspaceSlug: string) => {
  const { allowPermissions } = useUserPermissions();
  return allowPermissions([EUserPermissions.ADMIN], EUserPermissionsLevel.WORKSPACE, workspaceSlug);
};

export function Card(props: { title?: ReactNode; action?: ReactNode; className?: string; children: ReactNode }) {
  const { title, action, className, children } = props;
  return (
    <section className={cn("flex flex-col gap-3 rounded-lg border border-subtle bg-layer-1 p-4", className)}>
      {(title || action) && (
        <div className="flex items-center justify-between gap-2">
          {title && <h2 className="text-13 font-semibold text-secondary">{title}</h2>}
          {action}
        </div>
      )}
      {children}
    </section>
  );
}

/** Page title block with the breadcrumb trail of the mockups ("Clientes / Cliente"). */
export function PageTitle(props: {
  trail?: { label: string; href?: string }[];
  title: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
}) {
  const { trail, title, subtitle, actions } = props;
  return (
    <header className="flex flex-wrap items-center gap-4">
      <div className="flex min-w-0 flex-[1_1_320px] flex-col gap-1">
        {trail && trail.length > 0 && (
          <nav aria-label="Caminho" className="flex flex-wrap items-center gap-1 text-13 text-tertiary">
            {trail.map((item, index) => (
              <span key={`${item.href ?? ""}${item.label}`} className="flex items-center gap-1">
                {index > 0 && <span aria-hidden>/</span>}
                {item.href ? (
                  <Link href={item.href} className="hover:text-primary hover:underline">
                    {item.label}
                  </Link>
                ) : (
                  <span>{item.label}</span>
                )}
              </span>
            ))}
          </nav>
        )}
        <h1 className="text-20 font-semibold text-primary">{title}</h1>
        {subtitle && <div className="text-13 text-secondary">{subtitle}</div>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </header>
  );
}

export function EmptyState(props: { icon?: ReactNode; title: string; description?: ReactNode; action?: ReactNode }) {
  const { icon, title, description, action } = props;
  return (
    <div className="flex flex-col items-center gap-2 rounded-lg border border-dashed border-subtle px-4 py-8 text-center">
      {icon && <div className="text-tertiary">{icon}</div>}
      <p className="text-13 font-medium text-primary">{title}</p>
      {description && <p className="max-w-md text-12 text-tertiary">{description}</p>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}

/** Label + control + helper/error, stacked. */
export function Field(props: {
  label: string;
  htmlFor: string;
  helper?: ReactNode;
  error?: string;
  className?: string;
  children: ReactNode;
}) {
  const { label, htmlFor, helper, error, className, children } = props;
  return (
    <div className={cn("flex flex-col gap-1", className)}>
      <label htmlFor={htmlFor} className="text-12 font-medium text-secondary">
        {label}
      </label>
      {children}
      {error ? (
        <span className="text-11 text-danger-primary">{error}</span>
      ) : (
        helper && <span className="text-11 text-tertiary">{helper}</span>
      )}
    </div>
  );
}

/** Modal with a form: title, fields and the Cancelar / submit footer. */
export function FormModal(props: {
  isOpen: boolean;
  title: string;
  description?: ReactNode;
  submitLabel: string;
  isSubmitting: boolean;
  submitDisabled?: boolean;
  submitVariant?: "primary" | "error-fill";
  width?: EModalWidth;
  onClose: () => void;
  onSubmit: () => void | Promise<void>;
  children: ReactNode;
}) {
  const {
    isOpen,
    title,
    description,
    submitLabel,
    isSubmitting,
    submitDisabled,
    submitVariant = "primary",
    width = EModalWidth.XL,
    onClose,
    onSubmit,
    children,
  } = props;

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (!isSubmitting && !submitDisabled) void onSubmit();
  };

  return (
    <ModalCore isOpen={isOpen} handleClose={onClose} position={EModalPosition.TOP} width={width}>
      <form onSubmit={handleSubmit} className="flex flex-col gap-4 p-5">
        <div className="flex flex-col gap-1">
          <h3 className="text-16 font-semibold text-primary">{title}</h3>
          {description && <p className="text-13 text-secondary">{description}</p>}
        </div>
        {children}
        <div className="flex justify-end gap-2 border-t border-subtle pt-4">
          <Button type="button" variant="secondary" size="lg" onClick={onClose} disabled={isSubmitting}>
            Cancelar
          </Button>
          <Button
            type="submit"
            variant={submitVariant}
            size="lg"
            loading={isSubmitting}
            disabled={isSubmitting || submitDisabled}
          >
            {submitLabel}
          </Button>
        </div>
      </form>
    </ModalCore>
  );
}

/** Pill with the color of a ledger kind / status. */
export function Chip(props: { className?: string; children: ReactNode }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2 py-0.5 text-11 font-semibold whitespace-nowrap",
        props.className
      )}
    >
      {props.children}
    </span>
  );
}
