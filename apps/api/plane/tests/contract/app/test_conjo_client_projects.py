# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""MAN-408: when a project changes client, the open debits of its work items follow it.

Nothing else moves: no estimate that was never charged, no debit reversed by hand, no expired history.
"""

# Fixtures are shared with test_conjo_billing (pytest injects them by name).
# ruff: noqa: F401, F811

import datetime
from decimal import Decimal
from unittest import mock

import pytest
from django.utils import timezone

from plane.app.views.conjo_billing import set_client_projects
from plane.db.models import (
    Client,
    ClientContract,
    ClientProject,
    HourLedgerEntry,
    IntakePortalBudget,
    IssueClient,
)
from plane.utils import conjo_billing as billing

from .test_conjo_billing import client_, make_contract, make_issue, project

D = Decimal
TODAY = datetime.date(2026, 9, 15)


@pytest.fixture(autouse=True)
def fixed_day():
    with (
        mock.patch("plane.utils.conjo_billing.today", return_value=TODAY),
        mock.patch("plane.bgtasks.conjo_billing_task.notify_low_balance.delay"),
    ):
        yield


@pytest.fixture
def new_client(workspace):
    client = Client.objects.create(workspace=workspace, name="Cliente novo")
    client.test_contract = make_contract(client)
    billing.ensure_monthly_credits(client.test_contract, TODAY)
    return client


def approve(issue, hours="8"):
    return IntakePortalBudget.objects.create(
        issue=issue,
        project_id=issue.project_id,
        estimated_hours=D(hours),
        status="APPROVED",
        approved_at=timezone.now(),
    )


def charge(issue, hours="8", on=TODAY):
    budget = approve(issue, hours)
    billing.debit_for_estimate(issue, budget.estimated_hours, on=on, budget=budget)
    return budget


@pytest.fixture
def debited(client_, project):
    """Work item of the project with an approved estimate debited from the current client."""
    contract = make_contract(client_)
    issue = make_issue(project)
    budget = charge(issue)
    return {"issue": issue, "budget": budget, "contract": contract}


def entries(contract, kind):
    return HourLedgerEntry.objects.filter(contract=contract, kind=kind)


def move(client_from, client_to, project):
    assert set_client_projects(client_from, []) is None
    assert set_client_projects(client_to, [str(project.id)]) is None


@pytest.mark.contract
class TestOpenDebitFollowsTheProject:
    def test_debit_moves_through_the_api(self, session_client, workspace, project, client_, new_client, debited):
        old, new = debited["contract"], new_client.test_contract
        before_old = billing.balance(old)
        before_new = billing.balance(new)
        base = f"/api/workspaces/{workspace.slug}/clients/"

        removal = session_client.put(f"{base}{client_.id}/projects/", {"project_ids": []}, format="json")
        link = session_client.put(f"{base}{new_client.id}/projects/", {"project_ids": [str(project.id)]}, format="json")

        assert removal.status_code == 200
        assert link.status_code == 200
        assert billing.balance(old) == before_old + D("8")
        assert billing.balance(new) == before_new - D("8")
        reversal = entries(old, HourLedgerEntry.REVERSAL).get(issue=debited["issue"])
        assert reversal.note == billing.PROJECT_MOVE_NOTE
        assert entries(new, HourLedgerEntry.DEBIT).filter(budget=debited["budget"]).count() == 1

    def test_project_without_client_gives_the_hours_back(self, client_, debited):
        before = billing.balance(debited["contract"])
        assert set_client_projects(client_, []) is None
        assert billing.balance(debited["contract"]) == before + D("8")
        assert billing.open_debit(debited["issue"]) is None

    def test_out_and_back_to_the_same_client_keeps_the_balance(self, client_, project, debited):
        before = billing.balance(debited["contract"])
        move(client_, client_, project)
        assert billing.balance(debited["contract"]) == before
        assert billing.open_debit(debited["issue"]).budget_id == debited["budget"].id

    def test_saving_the_same_projects_changes_nothing(self, client_, project, debited):
        count = HourLedgerEntry.objects.count()
        assert set_client_projects(client_, [str(project.id)]) is None
        assert HourLedgerEntry.objects.count() == count

    def test_failure_keeps_the_previous_client(self, client_, project, debited):
        with mock.patch("plane.utils.conjo_billing.reverse_debit", side_effect=RuntimeError):
            with pytest.raises(RuntimeError):
                set_client_projects(client_, [])
        assert ClientProject.objects.filter(client=client_, project=project).exists()
        assert billing.open_debit(debited["issue"]) is not None


@pytest.mark.contract
class TestWhatDoesNotMove:
    def test_item_with_its_own_client_stays(self, workspace, client_, project, debited):
        chosen = Client.objects.create(workspace=workspace, name="Cliente do card")
        contract = make_contract(chosen)
        issue = make_issue(project, "Chamado do cliente do card")
        IssueClient.objects.create(issue=issue, client=chosen, project_id=project.id, workspace_id=workspace.id)
        charge(issue, "2")
        before = billing.balance(contract)

        set_client_projects(client_, [])

        assert billing.balance(contract) == before
        assert billing.open_debit(issue).contract_id == contract.id

    def test_first_link_does_not_charge_old_estimates(self, project, new_client):
        issue = make_issue(project, "Orçamento antigo, antes do pacote")
        approve(issue)
        before = billing.balance(new_client.test_contract)

        assert set_client_projects(new_client, [str(project.id)]) is None

        assert billing.balance(new_client.test_contract) == before
        assert billing.open_debit(issue) is None

    def test_estimate_never_charged_on_a_debited_item_stays_uncharged(self, client_, project, new_client, debited):
        old_estimate = approve(debited["issue"], "5")
        before = billing.balance(new_client.test_contract)

        move(client_, new_client, project)

        assert billing.balance(new_client.test_contract) == before - D("8")
        assert not HourLedgerEntry.objects.filter(budget=old_estimate).exists()

    def test_debit_reversed_by_hand_is_not_charged_again(self, client_, project, new_client, debited):
        debit = HourLedgerEntry.objects.get(budget=debited["budget"], kind=HourLedgerEntry.DEBIT)
        billing.reverse_debit(debit, note="Cortesia", on=TODAY)
        before = billing.balance(new_client.test_contract)

        move(client_, new_client, project)

        assert billing.balance(new_client.test_contract) == before
        assert billing.open_debit(debited["issue"]) is None

    def test_debit_with_an_expired_lot_stays_with_who_consumed_it(self, client_, project, new_client):
        contract = make_contract(client_, months=1)
        issue = make_issue(project, "Entregue em julho")
        charge(issue, "10", on=datetime.date(2026, 7, 10))
        debit = billing.open_debit(issue)
        before_new = billing.balance(new_client.test_contract)

        move(client_, new_client, project)

        assert billing.open_debit(issue).pk == debit.pk
        assert billing.balance(new_client.test_contract) == before_new
        assert not entries(contract, HourLedgerEntry.REVERSAL).exists()

    def test_debit_of_a_closed_contract_stays(self, client_, project, new_client, debited):
        ClientContract.objects.filter(pk=debited["contract"].pk).update(is_active=False)
        debit = billing.open_debit(debited["issue"])
        before_new = billing.balance(new_client.test_contract)

        move(client_, new_client, project)

        assert billing.open_debit(debited["issue"]).pk == debit.pk
        assert billing.balance(new_client.test_contract) == before_new
