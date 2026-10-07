# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Several estimates per portal ticket (additional scope, new estimate after a rejection) and formatted notes."""

from decimal import Decimal
from unittest import mock

import pytest
from django.core.cache import cache
from django.db import IntegrityError, transaction
from rest_framework.test import APIClient

from plane.db.models import (
    Client,
    ClientContact,
    ClientContract,
    ClientProject,
    HourLedgerEntry,
    Intake,
    IntakeIssue,
    IntakePortal,
    IntakePortalBudget,
    Issue,
    IssueWorkKind,
    Project,
    ProjectMember,
    State,
)
from plane.db.models.intake import SourceType
from plane.space.views.portal_auth import create_session
from plane.utils import conjo_billing as billing
from plane.utils.intake_portal import note_blocks, note_to_html, request_portal_budget

D = Decimal
EMAIL = "maria@cliente.com.br"


@pytest.fixture(autouse=True)
def fresh_throttle():
    # the portal endpoints are rate limited per client; each test starts clean
    cache.clear()
    yield


@pytest.fixture(autouse=True)
def quiet():
    with (
        mock.patch("plane.bgtasks.conjo_billing_task.notify_low_balance.delay"),
        mock.patch("plane.bgtasks.intake_portal_task.send_portal_budget_request.delay") as mail,
        mock.patch("plane.space.views.portal_tickets.issue_activity.delay"),
    ):
        yield mail


@pytest.fixture
def setup(db, workspace, create_user):
    project = Project.objects.create(name="Fretes", identifier="ORC", workspace=workspace, created_by=create_user)
    ProjectMember.objects.create(project=project, member=create_user, role=20, is_active=True)
    State.objects.create(name="A fazer", group="unstarted", project=project, workspace=workspace, default=True)
    client = Client.objects.create(workspace=workspace, name="Cliente")
    ClientProject.objects.create(workspace=workspace, client=client, project=project)
    ClientContact.objects.create(workspace=workspace, client=client, name="Maria", email=EMAIL, can_approve=True)
    contract = ClientContract.objects.create(
        workspace=workspace,
        client=client,
        name="Pacote 20h",
        hours_per_month=D("20"),
        starts_on=billing.month_start(billing.today()),
    )
    billing.refresh_contract(contract)
    intake = Intake.objects.create(name="Entrada", project=project, workspace=workspace)
    portal = IntakePortal.objects.create(project=project, workspace=workspace, intake=intake, is_enabled=True)
    issue = Issue.objects.create(name="Pedido", project=project)
    ticket = IntakeIssue.objects.create(
        project=project, workspace=workspace, intake=intake, issue=issue, source=SourceType.PORTAL, source_email=EMAIL
    )
    return {"project": project, "contract": contract, "portal": portal, "issue": issue, "ticket": ticket}


def send(setup, hours, note=""):
    budget, error = request_portal_budget(setup["ticket"], hours, note)
    assert error is None, error
    return budget


def answer(setup, action, budget_id=None, reason=""):
    portal = setup["portal"]
    token = create_session(EMAIL, portal.workspace_id, portal.project_id)
    url = f"/api/public/intake-portal/{portal.anchor}/tickets/{setup['issue'].id}/budget/{action}/"
    body = {}
    if budget_id:
        body["budget_id"] = str(budget_id)
    if reason:
        body["reason"] = reason
    return APIClient().post(url, body, format="json", HTTP_X_PORTAL_TOKEN=token)


@pytest.mark.contract
class TestSeveralEstimates:
    def test_additional_estimate_after_approval_debits_only_its_hours(self, setup, quiet):
        first = send(setup, "8")
        assert answer(setup, "approve").status_code == 200
        assert billing.balance(setup["contract"]) == D("12")

        extra = send(setup, "5", "Tela extra pedida depois")
        assert extra.id != first.id and extra.status == "PENDING"
        first.refresh_from_db()
        assert first.status == "APPROVED" and first.estimated_hours == D("8")  # never repriced
        quiet.assert_called_with(str(setup["issue"].id), budget_id=str(extra.id))

        assert answer(setup, "approve").status_code == 200
        assert billing.balance(setup["contract"]) == D("7")
        debits = HourLedgerEntry.objects.filter(issue_id=setup["issue"].id, kind="debit").order_by("created_at")
        assert [(d.budget_id, d.hours) for d in debits] == [(first.id, D("-8")), (extra.id, D("-5"))]

    def test_pending_estimate_is_revised_in_place(self, setup):
        first = send(setup, "8")
        revised = send(setup, "6", "Menos escopo")
        assert revised.id == first.id
        assert IntakePortalBudget.objects.filter(issue=setup["issue"]).count() == 1
        assert revised.estimated_hours == D("6")

    def test_new_estimate_after_a_rejection_keeps_the_history(self, setup):
        send(setup, "8")
        assert answer(setup, "reject", reason="Caro").status_code == 200
        send(setup, "6")
        statuses = list(
            IntakePortalBudget.objects.filter(issue=setup["issue"])
            .order_by("created_at")
            .values_list("status", flat=True)
        )
        assert statuses == ["REJECTED", "PENDING"]

    def test_only_one_pending_estimate_per_ticket(self, setup):
        send(setup, "8")
        with pytest.raises(IntegrityError), transaction.atomic():
            IntakePortalBudget.objects.create(
                issue=setup["issue"], project=setup["project"], estimated_hours=D("3"), status="PENDING"
            )

    def test_answering_a_decided_estimate_by_id_is_refused(self, setup):
        first = send(setup, "8")
        answer(setup, "approve")
        send(setup, "2")
        assert answer(setup, "approve", budget_id=first.id).status_code == 400
        assert billing.balance(setup["contract"]) == D("12")

    def test_kind_change_reverses_and_restores_every_estimate(self, setup):
        send(setup, "8")
        answer(setup, "approve")
        send(setup, "4")
        answer(setup, "approve")
        assert billing.balance(setup["contract"]) == D("8")

        billing.change_work_kind(setup["issue"], IssueWorkKind.MAINTENANCE)
        assert billing.balance(setup["contract"]) == D("20")
        assert not billing.open_debits(setup["issue"]).exists()

        billing.change_work_kind(setup["issue"], IssueWorkKind.EVOLUTION)
        assert billing.balance(setup["contract"]) == D("8")
        assert billing.open_debits(setup["issue"]).count() == 2

    def test_reversing_one_estimate_keeps_the_excess_of_the_other(self, setup):
        send(setup, "18")
        answer(setup, "approve")
        send(setup, "5")  # 2h left in the package: 3h excess
        answer(setup, "approve")
        excess = HourLedgerEntry.objects.get(issue_id=setup["issue"].id, kind="excess")
        first_debit = billing.open_debits(setup["issue"]).first()
        billing.reverse_debit(first_debit)
        assert HourLedgerEntry.objects.filter(pk=excess.pk).exists()

    def test_team_and_portal_see_the_history(self, setup, session_client, workspace):
        send(setup, "8")
        answer(setup, "approve")
        send(setup, "3")
        url = (
            f"/api/workspaces/{workspace.slug}/projects/{setup['project'].id}/issues/{setup['issue'].id}/portal-budget/"
        )
        data = session_client.get(url).json()
        assert [b["status"] for b in data["budgets"]] == ["APPROVED", "PENDING"]
        assert data["budget"]["status"] == "PENDING" and data["approved_hours"] == 8.0

        portal = setup["portal"]
        token = create_session(EMAIL, portal.workspace_id, portal.project_id)
        detail = APIClient().get(
            f"/api/public/intake-portal/{portal.anchor}/tickets/{setup['issue'].id}/", HTTP_X_PORTAL_TOKEN=token
        )
        assert detail.status_code == 200, detail.content
        assert len(detail.json()["budgets"]) == 2 and detail.json()["approved_hours"] == 8.0

        time = session_client.get(
            f"/api/workspaces/{workspace.slug}/projects/{setup['project'].id}/issues/{setup['issue'].id}/time/"
        ).json()
        assert time["budget"]["hours"] == "8.00" and time["budget"]["pending_hours"] == "3.00"


@pytest.mark.contract
class TestEstimateTimeline:
    def test_editing_keeps_the_previous_values_in_the_timeline(self, setup, create_user):
        budget, _ = request_portal_budget(setup["ticket"], "8", "- tela A", actor_id=create_user.id)
        request_portal_budget(setup["ticket"], "6", "- tela A\n- sem relatório", actor_id=create_user.id)
        events = list(budget.events.order_by("occurred_at"))
        assert [e.kind for e in events] == ["sent", "revised"]
        assert events[1].previous_hours == D("8") and events[1].hours == D("6")
        assert events[1].previous_note == "- tela A" and events[1].actor_id == create_user.id

    def test_resending_without_changes_is_refused(self, setup):
        send(setup, "8", "x")
        budget, error = request_portal_budget(setup["ticket"], "8", "x")
        assert budget is None and "Nada mudou" in error

    def test_client_answer_closes_the_timeline_and_hides_team_names(self, setup, create_user):
        request_portal_budget(setup["ticket"], "8", "", actor_id=create_user.id)
        request_portal_budget(setup["ticket"], "7", "", actor_id=create_user.id)
        assert answer(setup, "approve").status_code == 200
        portal = setup["portal"]
        token = create_session(EMAIL, portal.workspace_id, portal.project_id)
        detail = (
            APIClient()
            .get(f"/api/public/intake-portal/{portal.anchor}/tickets/{setup['issue'].id}/", HTTP_X_PORTAL_TOKEN=token)
            .json()
        )
        events = detail["budget"]["events"]
        assert [e["kind"] for e in events] == ["sent", "revised", "approved"]
        assert events[0]["actor"] == "Equipe" and events[2]["actor"] == EMAIL
        assert events[1]["previous_hours"] == 8.0 and detail["budget"]["can_edit"] is False

    def test_team_sees_who_edited(self, setup, create_user, session_client, workspace):
        request_portal_budget(setup["ticket"], "8", "", actor_id=create_user.id)
        url = (
            f"/api/workspaces/{workspace.slug}/projects/{setup['project'].id}/issues/{setup['issue'].id}/portal-budget/"
        )
        response = session_client.post(url, {"estimated_hours": 5, "note": "menos"}, format="json")
        assert response.status_code == 200
        events = session_client.get(url).json()["budget"]["events"]
        assert events[-1]["kind"] == "revised" and events[-1]["actor"] != "Equipe"
        assert events[-1]["note_changed"] is True


@pytest.mark.unit
class TestNoteFormatting:
    def test_blocks(self):
        text = "Escopo:\n- login\n- cadastro\n\n1. testes\n2) deploy\nlinha a\nlinha b"
        assert note_blocks(text) == [
            ("p", ["Escopo:"]),
            ("ul", ["login", "cadastro"]),
            ("ol", ["testes", "deploy"]),
            ("p", ["linha a", "linha b"]),
        ]

    def test_html_is_escaped(self):
        html = note_to_html("- **ok** <script>alert(1)</script>")
        assert "<strong>ok</strong>" in html and "<script>" not in html and "&lt;script&gt;" in html
