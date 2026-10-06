# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Hour packages: daily credits and expirations, debit on approved estimates and low balance notices."""

# Python imports
import logging
from decimal import Decimal
from uuid import uuid4

# Third party imports
from celery import shared_task

# Django imports
from django.utils.html import escape

# Module imports
from plane.utils import conjo_billing as billing
from plane.utils.exception_logger import log_exception

logger = logging.getLogger("plane.worker")


def _hours(value):
    """ "12.50" -> "12,5", "0" -> "0" (Brazilian notation, no trailing zeros)."""
    text = f"{Decimal(value).normalize():f}"
    return text.replace(".", ",")


@shared_task
def refresh_hour_packages():
    """Daily: credit the month when due and write off expired lots, for every active contract."""
    from plane.db.models import ClientContract

    for contract in ClientContract.objects.filter(is_active=True):
        try:
            billing.refresh_contract(contract)
        except Exception as e:
            log_exception(e)


def debit_approved_estimate(issue_id, hours, approved_by_email):
    """Called when the requester approves an estimate on the portal; never raises."""
    from plane.db.models import Issue

    try:
        issue = Issue.objects.filter(pk=issue_id).select_related("project").first()
        if issue is None:
            return None
        debit = billing.debit_for_estimate(issue, hours, approved_by_email)
        if debit is not None:
            notify_low_balance.delay(str(debit.contract_id), str(issue.project_id))
        return debit
    except Exception as e:
        log_exception(e)
        return None


@shared_task
def notify_low_balance(contract_id, project_id):
    """Post in the project's chat room when the package goes under its warning threshold."""
    from plane.db.models import ClientContract, ProjectChatIntegration
    from plane.utils.conjo_chat import is_configured, send_html_message

    try:
        contract = ClientContract.objects.filter(pk=contract_id).select_related("client").first()
        if contract is None or not is_configured():
            return
        summary = billing.package_summary(contract)
        if not summary["low_balance"]:
            return
        integration = ProjectChatIntegration.objects.filter(project_id=project_id).first()
        if integration is None or not integration.enabled or not integration.room_id:
            return
        available = _hours(summary["available"])
        client = contract.client.name
        html = (
            f"<b>Saldo baixo</b> no pacote de <b>{escape(client)}</b>: {escape(available)}h disponíveis "
            f"de {escape(_hours(summary['hours_per_month']))}h por mês."
        )
        body = f"Saldo baixo no pacote de {client}: {available}h disponíveis."
        send_html_message(integration.room_id, html, body, txn_id=uuid4().hex)
    except Exception as e:
        log_exception(e)
