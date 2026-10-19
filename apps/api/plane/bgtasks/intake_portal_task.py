# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Python imports
from urllib.parse import quote

# Third party imports
from celery import shared_task

# Django imports
from django.conf import settings
from django.utils.html import escape, strip_tags

# Module imports
from plane.db.models import IntakeIssue, IntakePortal, IntakePortalBudget, Issue, IssueComment
from plane.db.models.intake import IntakePortalBudgetStatus, SourceType
from plane.utils.exception_logger import log_exception
from plane.utils.intake_portal import approved_hours, note_to_html
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

    # Em produção só existe TASKS_PUBLIC_URL (o portal mora em <TASKS_PUBLIC_URL>/spaces/); sem ela o
    # link saía vazio e o e-mail ia sem botão (MAN-332).
    base_origin = (
        settings.SPACE_BASE_URL
        or settings.WEB_URL
        or settings.APP_BASE_URL
        or getattr(settings, "TASKS_PUBLIC_URL", "")
    )
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


def _requester_portal_url(intake_issue, issue_id) -> str:
    """Link do chamado no portal. Chamado sem o identificador do portal gravado usa o do portal da entrada."""
    anchor = ""
    if isinstance(intake_issue.extra, dict):
        anchor = intake_issue.extra.get("portal_anchor") or ""
    if not anchor and intake_issue.intake_id:
        anchor = (
            IntakePortal.objects.filter(intake_id=intake_issue.intake_id).values_list("anchor", flat=True).first() or ""
        )
    return _portal_ticket_url(anchor, str(issue_id))


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
        f'<div style="{BASE_STYLE}">'
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

        effective_portal_url = portal_url or _requester_portal_url(intake_issue, issue_id)

        link_html = _portal_cta_html(effective_portal_url, "Abrir chamado no portal") if effective_portal_url else ""
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

        effective_portal_url = portal_url or _requester_portal_url(intake_issue, issue_id)

        state_html = (
            f"<p>Status atual: <strong>{escape(issue.state.name)}</strong></p>"
            if issue.state_id and issue.state
            else ""
        )
        link_html = (
            _portal_cta_html(effective_portal_url, "Abrir atualização no portal") if effective_portal_url else ""
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


REPLY_TEXT_MAX = 1500


def _reply_text(comment_html: str) -> str:
    """Texto puro da resposta, com as quebras de parágrafo, cortado para caber no e-mail."""
    html = comment_html or ""
    for tag in ("</p>", "<br>", "<br/>", "<br />", "</li>", "</div>", "</h1>", "</h2>", "</h3>"):
        html = html.replace(tag, f"{tag}\n")
    text = "\n".join(line.strip() for line in strip_tags(html).splitlines())
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")
    text = text.strip()
    return text if len(text) <= REPLY_TEXT_MAX else f"{text[: REPLY_TEXT_MAX - 1].rstrip()}…"


@shared_task
def send_portal_ticket_reply(issue_id, comment_id, portal_url=""):
    """A equipe respondeu publicamente: o cliente recebe a resposta no e-mail e o botão para responder."""
    try:
        issue = Issue.objects.filter(pk=issue_id).select_related("state").first()
        if issue is None:
            return

        intake_issue = IntakeIssue.objects.filter(issue_id=issue_id, source=SourceType.PORTAL).first()
        if intake_issue is None or not intake_issue.source_email:
            return

        # Só resposta pública: nota interna nunca chega ao cliente.
        comment = IssueComment.objects.filter(pk=comment_id, issue_id=issue_id, access="EXTERNAL").first()
        if comment is None:
            return

        text = _reply_text(comment.comment_html)
        effective_portal_url = portal_url or _requester_portal_url(intake_issue, issue_id)
        reply_html = (
            '<div style="background:#f3f4f6;border-left:4px solid #1080bc;border-radius:6px;'
            'padding:12px 16px;margin:16px 0;white-space:pre-line;">'
            f"{escape(text)}"
            "</div>"
            if text
            else ""
        )
        state_html = (
            f"<p>Status atual: <strong>{escape(issue.state.name)}</strong></p>"
            if issue.state_id and issue.state
            else ""
        )
        link_html = _portal_cta_html(effective_portal_url, "Ver e responder no portal") if effective_portal_url else ""
        body = (
            f"<p>A equipe respondeu sua solicitação <strong>{escape(issue.name)}</strong>:</p>"
            f"{reply_html}"
            f"{state_html}"
            f"{link_html}"
        )
        send_transactional_email(
            intake_issue.source_email,
            f"Nova resposta no seu chamado: {issue.name}",
            _wrap("Nova resposta no seu chamado", body),
        )
    except Exception as e:
        log_exception(e)


def _hours_label(value):
    return f"{value:.2f}".rstrip("0").rstrip(".")


@shared_task
def send_portal_budget_request(issue_id, portal_url="", budget_id=None):
    """Ask the requester to approve the hourly estimate of their ticket."""
    try:
        issue = Issue.objects.filter(pk=issue_id).first()
        if issue is None:
            return

        intake_issue = IntakeIssue.objects.filter(issue_id=issue_id, source=SourceType.PORTAL).first()
        if intake_issue is None or not intake_issue.source_email:
            return

        budgets = IntakePortalBudget.objects.filter(issue_id=issue_id)
        budget = (
            budgets.filter(pk=budget_id).first()
            if budget_id
            else budgets.filter(status=IntakePortalBudgetStatus.PENDING).first()
        )
        if budget is None or budget.status != IntakePortalBudgetStatus.PENDING:
            return
        already_approved = approved_hours(list(budgets))
        last_event = budget.events.order_by("-occurred_at").first()
        revised_from = last_event.previous_hours if last_event and last_event.kind == "revised" else None

        effective_portal_url = portal_url or _requester_portal_url(intake_issue, issue_id)

        hours = f"{budget.estimated_hours:.2f}".rstrip("0").rstrip(".")
        note_html = (
            '<div style="background:#f9fafb;border-left:3px solid #d1d5db;padding:12px 16px;margin:0 0 16px;">'
            f"{note_to_html(budget.note)}</div>"
            if budget.note
            else ""
        )
        approved = f"{already_approved:.2f}".rstrip("0").rstrip(".")
        additional_html = (
            f"<p>Este é um orçamento adicional: {escape(approved)} horas já foram aprovadas neste chamado.</p>"
            if already_approved > 0
            else ""
        )
        link_html = (
            _portal_cta_html(effective_portal_url, "Revisar e aprovar no portal") if effective_portal_url else ""
        )
        intro_html = (
            f"<p>Revisamos o orçamento da sua solicitação <strong>{escape(issue.name)}</strong>"
            f" (antes: {escape(_hours_label(revised_from))} horas).</p>"
            if revised_from is not None
            else f"<p>Preparamos um orçamento para a sua solicitação <strong>{escape(issue.name)}</strong>.</p>"
        )
        body = (
            f"{intro_html}"
            f"{additional_html}"
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
            f"{'Orçamento revisado' if revised_from is not None else 'Aprovação de orçamento'}: {issue.name}",
            _wrap("Orçamento revisado" if revised_from is not None else "Orçamento aguardando sua aprovação", body),
        )
    except Exception as e:
        log_exception(e)


@shared_task
def send_portal_budget_cancelled(issue_id, budget_id, portal_url=""):
    """Tell the requester that the team cancelled an estimate (Conjo): it can no longer be approved."""
    try:
        issue = Issue.objects.filter(pk=issue_id).first()
        if issue is None:
            return

        intake_issue = IntakeIssue.objects.filter(issue_id=issue_id, source=SourceType.PORTAL).first()
        if intake_issue is None or not intake_issue.source_email:
            return

        budget = IntakePortalBudget.objects.filter(pk=budget_id, issue_id=issue_id).first()
        if budget is None or budget.status != IntakePortalBudgetStatus.CANCELLED:
            return

        effective_portal_url = portal_url or _requester_portal_url(intake_issue, issue_id)

        hours = _hours_label(budget.estimated_hours)
        reason_html = (
            '<div style="background:#f9fafb;border-left:3px solid #d1d5db;padding:12px 16px;margin:0 0 16px;">'
            f'<p style="margin:0;"><strong>Motivo:</strong> {escape(budget.cancellation_reason)}</p></div>'
            if budget.cancellation_reason
            else ""
        )
        link_html = _portal_cta_html(effective_portal_url, "Abrir chamado no portal") if effective_portal_url else ""
        body = (
            f"<p>A equipe cancelou o orçamento da sua solicitação <strong>{escape(issue.name)}</strong>.</p>"
            '<p style="font-size:28px;font-weight:700;background:#f3f4f6;padding:16px 24px;'
            'border-radius:8px;text-align:center;margin:24px 0;color:#6b7280;text-decoration:line-through;">'
            f"{escape(hours)} horas"
            "</p>"
            f"{reason_html}"
            "<p>Este orçamento não precisa mais de resposta e não pode mais ser aprovado. Nenhuma hora foi "
            "descontada por ele. Se for preciso, a equipe enviará um novo orçamento.</p>"
            f"{link_html}"
        )
        send_transactional_email(
            intake_issue.source_email,
            f"Orçamento cancelado: {issue.name}",
            _wrap("Orçamento cancelado", body),
        )
    except Exception as e:
        log_exception(e)
