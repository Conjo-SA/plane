# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Conjo: the activity report by e-mail (CONJO-52).

On the first business day of the month every active client with the monthly report turned on gets the
previous month's report, as a PDF, at the contacts marked to receive it. A person can also send it by hand
for any period (a resend). Each e-mail is a ``ClientReportDelivery`` row:

- The monthly row of a client and period is unique and only a ``pending`` row is sent, after being moved
  to ``sending`` under a row lock. A worker restart, a second beat run or a retry never sends it twice.
- A row left in ``sending`` (the worker died mid-send) is never resent by itself: the team is told to
  check whether it arrived, and a manual send is a new row.
- A failure where nothing went out is retried; one where the provider may have taken the message is not.
- Items without a kind block the report (the client would get hours missing); the team is told.
- Outside production (``CONJO_REPORT_MODE`` other than ``live``) the e-mail goes only to the test address.
"""

# Python imports
import datetime
import logging
from uuid import uuid4

# Django imports
from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.html import escape

# Module imports
from plane.utils import conjo_billing as billing
from plane.utils.conjo_business_days import first_business_day
from plane.utils.conjo_client_report import build_client_report
from plane.utils.conjo_client_report_pdf import hours_text, period_text, render_client_report_pdf
from plane.utils.exception_logger import log_exception
from plane.utils.mailjet import EmailDeliveryError, send_email_with_attachments

logger = logging.getLogger("plane.worker")

# Days after the first business day in which a monthly report still goes out (the worker was down).
CATCH_UP_DAYS = 3
MAX_ATTEMPTS = 4
RETRY_MINUTES = 15
STUCK_AFTER = datetime.timedelta(hours=1)
# A row still waiting this long lost its queue message (broker down, retry lost): queue it again.
LOST_AFTER = datetime.timedelta(hours=2)

RETRY = "retry"


def previous_month(today):
    end = billing.month_start(today) - datetime.timedelta(days=1)
    return billing.month_start(end), end


def monthly_due(today):
    """True from the first business day of the month until ``CATCH_UP_DAYS`` after it."""
    first = first_business_day(today.year, today.month)
    return first <= today <= first + datetime.timedelta(days=CATCH_UP_DAYS)


def is_live():
    return settings.CONJO_REPORT_MODE == "live"


def report_recipients(client):
    """E-mails of the contacts marked to receive the report, without repetitions."""
    seen, emails = set(), []
    for email in client.contacts.filter(receives_report=True).exclude(email="").values_list("email", flat=True):
        email = email.strip()
        if email and email.lower() not in seen:
            seen.add(email.lower())
            emails.append(email)
    return emails


# --------------------------------------------------------------------------- #
# Scheduling
# --------------------------------------------------------------------------- #


def release_stuck(now=None):
    """Rows left in ``sending`` by a dead worker become ``failed`` (never resent by themselves)."""
    from plane.db.models import ClientReportDelivery

    now = now or timezone.now()
    stuck = Q(status=ClientReportDelivery.SENDING, updated_at__lt=now - STUCK_AFTER)
    released = []
    for delivery_id in ClientReportDelivery.objects.filter(stuck).values_list("id", flat=True):
        with transaction.atomic():
            # Checked again under the lock: a slow worker may have finished meanwhile.
            delivery = (
                ClientReportDelivery.objects.select_for_update()
                .select_related("client")
                .filter(stuck, pk=delivery_id)
                .first()
            )
            if delivery is None:
                continue
            _finish(
                delivery,
                ClientReportDelivery.FAILED,
                "O envio foi interrompido e não dá para saber se o e-mail saiu. Confira com o cliente antes de "
                "reenviar.",
            )
        alert_team(delivery, delivery.reason)
        released.append(delivery)
    return released


def lost_pending(now=None):
    """Ids of rows (monthly or by hand) waiting longer than a queue message can take."""
    from plane.db.models import ClientReportDelivery

    now = now or timezone.now()
    rows = ClientReportDelivery.objects.filter(status=ClientReportDelivery.PENDING, updated_at__lt=now - LOST_AFTER)
    return [str(pk) for pk in rows.values_list("id", flat=True)]


def schedule_monthly(today=None):
    """Create (once) the monthly rows of the previous month; returns the ids still waiting to be sent."""
    from plane.db.models import Client, ClientReportDelivery

    today = today or billing.today()
    if not monthly_due(today):
        return []
    start, end = previous_month(today)
    pending = []
    for client in Client.objects.filter(is_active=True, monthly_report_enabled=True):
        try:
            with transaction.atomic():
                delivery, _ = ClientReportDelivery.objects.get_or_create(
                    client=client,
                    period_start=start,
                    period_end=end,
                    trigger=ClientReportDelivery.AUTO,
                    defaults={"workspace_id": client.workspace_id},
                )
        except IntegrityError:
            # Another run created it at the same time; that run sends it.
            continue
        if delivery.status == ClientReportDelivery.PENDING:
            pending.append(str(delivery.id))
    return pending


def request_manual(client, start, end, user):
    """A send by hand (also a resend); always a new row."""
    from plane.db.models import ClientReportDelivery

    return ClientReportDelivery.objects.create(
        client=client,
        workspace_id=client.workspace_id,
        period_start=start,
        period_end=end,
        trigger=ClientReportDelivery.MANUAL,
        created_by=user,
    )


# --------------------------------------------------------------------------- #
# Sending
# --------------------------------------------------------------------------- #


def _claim(delivery_id):
    """Move a ``pending`` row to ``sending`` under a lock; ``None`` when it is not ours to send."""
    from plane.db.models import ClientReportDelivery

    with transaction.atomic():
        delivery = (
            ClientReportDelivery.objects.select_for_update().select_related("client").filter(pk=delivery_id).first()
        )
        if delivery is None or delivery.status != ClientReportDelivery.PENDING:
            return None
        delivery.status = ClientReportDelivery.SENDING
        delivery.attempts += 1
        delivery.save(update_fields=["status", "attempts", "updated_at"])
    return delivery


def _finish(delivery, status, reason="", alert=False, **fields):
    delivery.status = status
    delivery.reason = reason
    for name, value in fields.items():
        setattr(delivery, name, value)
    delivery.save(update_fields=["status", "reason", "updated_at", *fields])
    if alert:
        alert_team(delivery, reason)
    return status


def deliver(delivery_id):
    """Send one row. Returns its final status, or ``RETRY`` when the task should try again later."""
    from plane.db.models import ClientReportDelivery as Delivery

    delivery = _claim(delivery_id)
    if delivery is None:
        return None
    client = delivery.client
    try:
        if delivery.trigger == Delivery.AUTO and not (client.is_active and client.monthly_report_enabled):
            return _finish(delivery, Delivery.SKIPPED, "Envio mensal desligado para o cliente.")
        recipients = report_recipients(client)
        if not recipients:
            return _finish(
                delivery,
                Delivery.SKIPPED,
                "Nenhum contato do cliente está marcado para receber o relatório.",
                alert=True,
            )
        report = build_client_report(
            client, delivery.period_start, delivery.period_end, billing.client_project_ids(client)
        )
        delivery.number = report["number"]
        delivery.recipients = recipients
        unclassified = [w for w in report["warnings"] if w["type"] == "unclassified"]
        if unclassified:
            keys = ", ".join(item["key"] for item in unclassified[0]["items"][:10])
            return _finish(
                delivery,
                Delivery.SKIPPED,
                f"Há chamados com horas e sem tipo (evolução ou manutenção): {keys}. Classifique-os e envie de "
                "novo pela tela do cliente.",
                alert=True,
                number=delivery.number,
                recipients=recipients,
            )
        if report["totals"]["items"] == 0 and report["package"] is None:
            return _finish(
                delivery,
                Delivery.SKIPPED,
                "Sem atividade no período e sem pacote de horas.",
                number=delivery.number,
                recipients=recipients,
            )
        if is_live():
            to, test_mode = recipients, False
        elif settings.CONJO_REPORT_TEST_EMAIL:
            to, test_mode = [settings.CONJO_REPORT_TEST_EMAIL], True
        else:
            return _finish(
                delivery,
                Delivery.SKIPPED,
                "Fora de produção os envios vão só para o endereço de teste, e nenhum está configurado "
                "(CONJO_REPORT_TEST_EMAIL).",
                number=delivery.number,
                recipients=recipients,
            )
        subject, html = report_email(report, recipients if test_mode else None)
        pdf = render_client_report_pdf(report)
        send_email_with_attachments(
            to,
            subject,
            html,
            [(f"Relatorio-{report['number']}.pdf", "application/pdf", pdf)],
            reply_to=settings.CONJO_REPORT_REPLY_TO or None,
        )
    except EmailDeliveryError as e:
        if e.retryable and delivery.attempts < MAX_ATTEMPTS:
            _finish(
                delivery,
                Delivery.PENDING,
                f"Tentativa {delivery.attempts} falhou, tentando de novo: {e}",
                number=delivery.number,
                recipients=delivery.recipients,
            )
            return RETRY
        reason = f"Falha no envio: {e}"
        if e.uncertain:
            reason += " Confira com o cliente antes de reenviar."
        return _finish(
            delivery, Delivery.FAILED, reason, alert=True, number=delivery.number, recipients=delivery.recipients
        )
    except Exception as e:
        log_exception(e)
        return _finish(delivery, Delivery.FAILED, f"Erro ao montar o relatório: {e}", alert=True)
    return _finish(
        delivery,
        Delivery.SENT,
        "",
        number=delivery.number,
        recipients=recipients,
        delivered_to=to,
        test_mode=test_mode,
        sent_at=timezone.now(),
    )


# --------------------------------------------------------------------------- #
# Messages
# --------------------------------------------------------------------------- #


def report_email(report, test_recipients=None):
    """Subject and HTML body. ``test_recipients``: who would get it in production (shown in a banner)."""
    client = report["client"].get("legal_name") or report["client"]["name"]
    period = period_text(report["period"]["from"], report["period"]["to"])
    totals, pkg = report["totals"], report["package"]
    subject = f"Relatório de atividades: {report['client']['name']}, {period.split(' (')[0]}"
    if test_recipients is not None:
        subject = f"[TESTE] {subject}"
    rows = [
        ("Horas no período", hours_text(totals["hours"])),
        ("Evolução", hours_text(totals["evolution_hours"])),
        ("Manutenção (incluída no contrato)", hours_text(totals["maintenance_hours"])),
        ("Chamados concluídos", f"{totals['done_items']} de {totals['items']}"),
    ]
    if pkg:
        balance = hours_text(pkg["balance"])
        if pkg.get("valid_until"):
            balance += f" (válido até {datetime.date.fromisoformat(pkg['valid_until']):%d/%m/%Y})"
        rows.append(("Saldo do pacote de horas", balance))
    table = "".join(
        f'<tr><td style="padding:6px 12px 6px 0;color:#6b6b66;">{escape(label)}</td>'
        f'<td style="padding:6px 0;font-weight:700;text-align:right;">{escape(value)}</td></tr>'
        for label, value in rows
    )
    banner = ""
    if test_recipients is not None:
        banner = (
            '<p style="background:#fff4e5;border:1px solid #f5c26b;border-radius:8px;padding:10px 12px;'
            'font-size:13px;margin:0 0 20px;">Envio de teste (fora de produção). Em produção este e-mail iria '
            f"para: {escape(', '.join(test_recipients))}.</p>"
        )
    reply = "<p>Qualquer dúvida, é só responder este e-mail.</p>" if settings.CONJO_REPORT_REPLY_TO else ""
    html = (
        "<div style=\"font-family:system-ui,-apple-system,'Segoe UI',sans-serif;color:#141414;line-height:1.6;"
        'max-width:560px;margin:0 auto;padding:24px;">'
        f"{banner}"
        "<p>Olá,</p>"
        f"<p>Segue o relatório de atividades de <b>{escape(client)}</b> referente a {escape(period)}.</p>"
        f'<table style="border-collapse:collapse;font-size:14px;margin:16px 0;">{table}</table>'
        "<p>O relatório completo, com o detalhamento de cada atividade, está no PDF anexo "
        f"(nº {escape(report['number'])}).</p>"
        f"{reply}"
        "<p>Equipe Conjo SA</p>"
        '<hr style="border:none;border-top:1px solid #ececec;margin:24px 0;" />'
        '<p style="font-size:12px;color:#8a8a84;margin:0;">Você recebe este relatório todo mês por ser contato '
        "de "
        f"{escape(report['client']['name'])} na Conjo SA.</p>"
        "</div>"
    )
    return subject, html


def _alert_room(client):
    from plane.db.models import ProjectChatIntegration

    if settings.CONJO_REPORT_ALERT_ROOM:
        return settings.CONJO_REPORT_ALERT_ROOM
    projects = client.client_projects.values_list("project_id", flat=True)
    integration = (
        ProjectChatIntegration.objects.filter(project_id__in=projects, enabled=True)
        .exclude(room_id="")
        .order_by("created_at")
        .first()
    )
    return integration.room_id if integration else None


def alert_team(delivery, reason):
    """Tell the team in the chat (the configured room, else the room of the client's first project)."""
    from plane.utils.conjo_chat import is_configured, send_html_message

    client = delivery.client
    period = period_text(delivery.period_start.isoformat(), delivery.period_end.isoformat())
    body = f"Relatório de {client.name} ({period}) não foi enviado: {reason}"
    logger.warning(body)
    try:
        room = _alert_room(client)
        if not room or not is_configured():
            return
        html = f"<b>Relatório de {escape(client.name)}</b> ({escape(period)}) não foi enviado: {escape(reason)}"
        send_html_message(room, html, body, txn_id=uuid4().hex)
    except Exception as e:
        log_exception(e)
