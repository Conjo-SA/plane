# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Python imports
from urllib.parse import quote

# Third party imports
from celery import shared_task

# Django imports
from django.conf import settings
from django.utils.html import escape

# Module imports
from plane.db.models import IntakeIssue, IntakePortalBudget, Issue
from plane.db.models.intake import IntakePortalBudgetStatus, SourceType
from plane.utils.exception_logger import log_exception
from plane.utils.mailjet import send_transactional_email

BASE_STYLE = (
    "font-family:system-ui,-apple-system,'Segoe UI',sans-serif;color:#1f2937;"
    "line-height:1.6;max-width:560px;margin:0 auto;padding:24px;"
)


def _normalize_base_path(base_path: str | None, fallback: str) -> str:
    normalized_path = base_path or fallback
    if not normalized_path.startswith("/"):
        normalized_path = f"/{normalized_path}"
    if not normalized_path.endswith("/"):
        normalized_path = f"{normalized_path}/"
    return normalized_path


def _portal_ticket_url(anchor: str | None, issue_id: str | None = None) -> str:
    if not anchor:
        return ""

    base_origin = settings.SPACE_BASE_URL or settings.WEB_URL or settings.APP_BASE_URL
    if not base_origin:
        return ""

    space_base_path = _normalize_base_path(getattr(settings, "SPACE_BASE_PATH", None), "/spaces/")
    safe_anchor = quote(str(anchor).strip(), safe="")
    if not safe_anchor:
        return ""

    ticket_path = f"portal/{safe_anchor}"
    if issue_id:
        ticket_path = f"{ticket_path}/{quote(str(issue_id).strip(), safe='')}"

    return f"{base_origin.rstrip('/')}{space_base_path}{ticket_path}"


def _portal_cta_html(portal_url: str, button_label: str) -> str:
    safe_url = escape(portal_url)
    safe_label = escape(button_label)
    return (
        '<div style="margin-top:20px;">'
        f'<a href="{safe_url}" '
        'style="display:inline-block;background:#1080bc;color:#ffffff;text-decoration:none;'
        'padding:10px 16px;border-radius:8px;font-weight:600;">'
        f"{safe_label}"
        "</a>"
        f'<p style="margin:12px 0 0;font-size:13px;color:#4b5563;">Ou acesse direto pelo link: <a href="{safe_url}" style="color:#1080bc;">{safe_url}</a></p>'
        "</div>"
    )


def _wrap(title, body_html):
    return (
        f"<div style=\"{BASE_STYLE}\">"
        f'<h1 style="font-size:20px;margin:0 0 16px;color:#111827;">{title}</h1>'
        f"{body_html}"
        '<hr style="border:none;border-top:1px solid #e5e7eb;margin:24px 0;" />'
        '<p style="font-size:12px;color:#6b7280;margin:0;">'
        "Você recebeu este e-mail porque abriu uma solicitação em nosso portal de atendimento."
        "</p>"
        "</div>"
    )


@shared_task
def send_portal_verification_code(email, code, project_name=""):
    """Email the one-time code used to confirm a requester address."""
    try:
        safe_project = escape(project_name or "")
        heading = f"Seu código de confirmação{f' — {safe_project}' if safe_project else ''}"
        body = (
            "<p>Use o código abaixo para confirmar seu e-mail e continuar sua solicitação.</p>"
            '<p style="font-size:32px;font-weight:700;letter-spacing:6px;'
            'background:#f3f4f6;padding:16px 24px;border-radius:8px;text-align:center;margin:24px 0;">'
            f"{escape(code)}"
            "</p>"
            "<p>O código expira em 10 minutos. Se você não fez esta solicitação, ignore este e-mail.</p>"
        )
        send_transactional_email(email, f"Código de confirmação: {code}", _wrap(heading, body))
    except Exception as e:
        log_exception(e)


@shared_task
def send_portal_ticket_created(issue_id, portal_url=""):
    """Confirm to the requester that the ticket was received."""
    try:
        issue = Issue.objects.filter(pk=issue_id).select_related("project").first()
        if issue is None:
            return

        intake_issue = IntakeIssue.objects.filter(issue_id=issue_id, source=SourceType.PORTAL).first()
        if intake_issue is None or not intake_issue.source_email:
            return

        portal_anchor = ""
        if isinstance(intake_issue.extra, dict):
            portal_anchor = intake_issue.extra.get("portal_anchor") or ""

        effective_portal_url = portal_url or _portal_ticket_url(portal_anchor, str(issue_id))

        link_html = (
            _portal_cta_html(effective_portal_url, "Abrir chamado no portal")
            if effective_portal_url
            else ""
        )
        body = (
            f"<p>Recebemos sua solicitação <strong>{escape(issue.name)}</strong>.</p>"
            "<p>Nossa equipe já foi notificada e você receberá um e-mail a cada atualização.</p>"
            f"{link_html}"
        )
        send_transactional_email(
            intake_issue.source_email,
            f"Recebemos sua solicitação: {issue.name}",
            _wrap("Solicitação recebida", body),
        )
    except Exception as e:
        log_exception(e)


@shared_task
def send_portal_ticket_update(issue_id, summary, portal_url=""):
    """Notify the requester that their ticket changed."""
    try:
        issue = Issue.objects.filter(pk=issue_id).select_related("state").first()
        if issue is None:
            return

        intake_issue = IntakeIssue.objects.filter(issue_id=issue_id, source=SourceType.PORTAL).first()
        if intake_issue is None or not intake_issue.source_email:
            return

        portal_anchor = ""
        if isinstance(intake_issue.extra, dict):
            portal_anchor = intake_issue.extra.get("portal_anchor") or ""

        effective_portal_url = portal_url or _portal_ticket_url(portal_anchor, str(issue_id))

        state_html = (
            f'<p>Status atual: <strong>{escape(issue.state.name)}</strong></p>' if issue.state_id and issue.state else ""
        )
        link_html = (
            _portal_cta_html(effective_portal_url, "Abrir atualização no portal")
            if effective_portal_url
            else ""
        )
        body = (
            f"<p>Sua solicitação <strong>{escape(issue.name)}</strong> foi atualizada.</p>"
            f"<p>{escape(summary)}</p>"
            f"{state_html}"
            f"{link_html}"
        )
        send_transactional_email(
            intake_issue.source_email,
            f"Atualização no chamado: {issue.name}",
            _wrap("Atualização no seu chamado", body),
        )
    except Exception as e:
        log_exception(e)


@shared_task
def send_portal_budget_request(issue_id, portal_url=""):
    """Ask the requester to approve the hourly estimate of their ticket."""
    try:
        issue = Issue.objects.filter(pk=issue_id).first()
        if issue is None:
            return

        intake_issue = IntakeIssue.objects.filter(issue_id=issue_id, source=SourceType.PORTAL).first()
        if intake_issue is None or not intake_issue.source_email:
            return

        budget = IntakePortalBudget.objects.filter(issue_id=issue_id).first()
        if budget is None or budget.status != IntakePortalBudgetStatus.PENDING:
            return

        portal_anchor = ""
        if isinstance(intake_issue.extra, dict):
            portal_anchor = intake_issue.extra.get("portal_anchor") or ""

        effective_portal_url = portal_url or _portal_ticket_url(portal_anchor, str(issue_id))

        hours = f"{budget.estimated_hours:.2f}".rstrip("0").rstrip(".")
        note_html = f"<p>{escape(budget.note)}</p>" if budget.note else ""
        link_html = (
            _portal_cta_html(effective_portal_url, "Revisar e aprovar no portal") if effective_portal_url else ""
        )
        body = (
            f"<p>Preparamos um orçamento para a sua solicitação <strong>{escape(issue.name)}</strong>.</p>"
            '<p style="font-size:28px;font-weight:700;background:#f3f4f6;padding:16px 24px;'
            'border-radius:8px;text-align:center;margin:24px 0;">'
            f"{escape(hours)} horas"
            "</p>"
            f"{note_html}"
            "<p>O trabalho só começa depois da sua aprovação. A aprovação é definitiva e não pode ser desfeita.</p>"
            f"{link_html}"
        )
        send_transactional_email(
            intake_issue.source_email,
            f"Aprovação de orçamento: {issue.name}",
            _wrap("Orçamento aguardando sua aprovação", body),
        )
    except Exception as e:
        log_exception(e)
