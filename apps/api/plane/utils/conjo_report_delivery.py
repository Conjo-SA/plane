# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Conjo: the activity report by e-mail (CONJO-52).

On the first business day of the month every active client with the monthly report turned on gets the
previous month's report, as a PDF, at the contacts marked to receive it. On the day their hour package
runs out they also get the report of the month so far. A person can also send it by hand for any period
(a resend). Each e-mail is a ``ClientReportDelivery`` row:

- The monthly row of a client and period is unique and only a ``pending`` row is sent, after being moved
  to ``sending`` under a row lock. A worker restart, a second beat run or a retry never sends it twice.
- A row left in ``sending`` (the worker died mid-send) is never resent by itself: the team is told to
  check whether it arrived, and a manual send is a new row.
- A failure where nothing went out is retried; one where the provider may have taken the message is not.
- Items without a kind block the report (the client would get hours missing); the team is told.
- Until ``CONJO_REPORT_MODE`` is ``live`` (test mode, also how production is checked before going
  live) every e-mail goes only to the test address and the monthly run does not happen: a monthly
  row sent to the test address would keep that month from ever reaching the client.
"""

# Python imports
import datetime
import logging
import os
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from uuid import uuid4

# Django imports
from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.html import escape

# Module imports
from plane.license.utils.instance_value import get_configuration_value
from plane.utils import conjo_billing as billing
from plane.utils.conjo_business_days import first_business_day
from plane.utils.conjo_client_report import build_client_report
from plane.utils.conjo_client_report_pdf import period_text, render_client_report_pdf
from plane.utils.conjo_report_email import inline_images, report_email
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

# How far back a debit can be and still count as the one that emptied the package (the daily run or two
# may have been missed). A report created after that debit means it was already handled.
EXHAUSTED_LOOKBACK = datetime.timedelta(days=2)

MAX_HOUR_RATE = Decimal("1000000")

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


def hour_rate():
    """Value of one hour, from the instance settings; ``None`` when it is empty or invalid."""
    (raw,) = get_configuration_value([{"key": "CONJO_HOUR_RATE", "default": os.environ.get("CONJO_HOUR_RATE", "")}])
    raw = str(raw or "").strip()
    if "," in raw:
        raw = raw.replace(".", "").replace(",", ".")
    try:
        rate = Decimal(raw)
    except InvalidOperation:
        return None
    # More than two decimals is a typo ("1.500" meaning 1500), and a huge number too.
    if not rate.is_finite() or not 0 < rate < MAX_HOUR_RATE or -rate.as_tuple().exponent > 2:
        return None
    return rate


def report_value(report):
    """Evolution hours at the hour rate. Maintenance is included in the contract, so it has no value."""
    rate = hour_rate()
    hours = Decimal(str(report["totals"]["evolution_hours"]))
    if rate is None or hours <= 0:
        return None
    total = (hours * rate).quantize(Decimal("0.01"), ROUND_HALF_UP)
    return {"hours": str(hours), "hour_rate": str(rate), "total": str(total)}


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
    if not is_live() or not monthly_due(today):
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


def schedule_exhausted(now=None):
    """Rows for the clients whose package ran out; returns the ids waiting to be sent.

    The package ran out when the balance is empty and the last thing that took hours from it was a debit
    (one with no hours left is only excess). An expiration or an adjustment after it means the hours
    ended some other way. The report covers the month of that debit, up to its day. Runs only in live
    mode, for the same reason as the monthly run.
    """
    from plane.db.models import ClientContract, ClientReportDelivery, HourLedgerEntry

    if not is_live():
        return []
    now = now or timezone.now()
    today = billing.local_date(now)
    debits = HourLedgerEntry.objects.filter(
        kind=HourLedgerEntry.DEBIT, hours__lt=0, reversals__isnull=True, created_at__gt=now - EXHAUSTED_LOOKBACK
    )
    contracts = ClientContract.objects.filter(
        is_active=True,
        client__is_active=True,
        client__monthly_report_enabled=True,
        pk__in=debits.values("contract_id"),
    ).select_related("client")
    pending = []
    for contract in contracts:
        if billing.balance(contract, today) > 0:
            continue
        last_debit = debits.filter(contract=contract).order_by("-created_at").first()
        if HourLedgerEntry.objects.filter(
            contract=contract,
            kind__in=[HourLedgerEntry.EXPIRATION, HourLedgerEntry.ADJUSTMENT],
            created_at__gt=last_debit.created_at,
        ).exists():
            continue
        already_handled = ClientReportDelivery.objects.filter(
            client=contract.client,
            trigger=ClientReportDelivery.EXHAUSTED,
            created_at__gte=last_debit.created_at,
        )
        if already_handled.exists():
            continue
        try:
            with transaction.atomic():
                delivery, _ = ClientReportDelivery.objects.get_or_create(
                    client=contract.client,
                    period_start=billing.month_start(last_debit.occurred_on),
                    period_end=last_debit.occurred_on,
                    trigger=ClientReportDelivery.EXHAUSTED,
                    defaults={"workspace_id": contract.workspace_id},
                )
        except IntegrityError:
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
        if delivery.trigger != Delivery.MANUAL and not (client.is_active and client.monthly_report_enabled):
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
        report["value"] = report_value(report)
        subject, html = report_email(
            report, recipients if test_mode else None, exhausted=delivery.trigger == Delivery.EXHAUSTED
        )
        pdf = render_client_report_pdf(report)
        send_email_with_attachments(
            to,
            subject,
            html,
            [(f"Relatorio-{report['number']}.pdf", "application/pdf", pdf)],
            reply_to=settings.CONJO_REPORT_REPLY_TO or None,
            inline=inline_images(),
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
# Team alerts
# --------------------------------------------------------------------------- #


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
