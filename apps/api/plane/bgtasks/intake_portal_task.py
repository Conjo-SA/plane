# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Third party imports
from celery import shared_task

# Django imports
from django.utils.html import escape

# Module imports
from plane.db.models import IntakeIssue, Issue
from plane.db.models.intake import SourceType
from plane.utils.exception_logger import log_exception
from plane.utils.mailjet import send_transactional_email

BASE_STYLE = (
    "font-family:system-ui,-apple-system,'Segoe UI',sans-serif;color:#1f2937;"
    "line-height:1.6;max-width:560px;margin:0 auto;padding:24px;"
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

        link_html = (
            f'<p><a href="{escape(portal_url)}" style="color:#1080bc;">Acompanhar meus chamados</a></p>'
            if portal_url
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

        state_html = (
            f'<p>Status atual: <strong>{escape(issue.state.name)}</strong></p>' if issue.state_id and issue.state else ""
        )
        link_html = (
            f'<p><a href="{escape(portal_url)}" style="color:#1080bc;">Ver detalhes do chamado</a></p>'
            if portal_url
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
