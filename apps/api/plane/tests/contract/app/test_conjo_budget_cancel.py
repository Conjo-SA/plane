# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""MAN-156: the team cancels a pending or rejected estimate (never an approved one)."""

import json
from decimal import Decimal
from unittest import mock

import pytest
from django.core.cache import cache
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
    IssueComment,
    Project,
    ProjectMember,
    State,
    User,
    WorkspaceMember,
)
from plane.db.models.intake import SourceType
from plane.mcp.models import MCPServer
from plane.space.views.portal_auth import create_session
from plane.utils import conjo_billing as billing
from plane.utils.intake_portal import request_portal_budget

D = Decimal
EMAIL = "maria@cliente.com.br"


@pytest.fixture(autouse=True)
def fresh_throttle():
    cache.clear()
    yield


@pytest.fixture(autouse=True)
def quiet():
    with (
        mock.patch("plane.bgtasks.conjo_billing_task.notify_low_balance.delay"),
        mock.patch("plane.bgtasks.intake_portal_task.send_portal_budget_request.delay") as request_mail,
        mock.patch("plane.bgtasks.intake_portal_task.send_portal_budget_cancelled.delay") as cancel_mail,
        mock.patch("plane.bgtasks.issue_activities_task.issue_activity.delay") as activity,
    ):
        yield {"request_mail": request_mail, "cancel_mail": cancel_mail, "activity": activity}


@pytest.fixture
def setup(db, workspace, create_user):
    project = Project.objects.create(name="Fretes", identifier="CAN", workspace=workspace, created_by=create_user)
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
        project=project,
        workspace=workspace,
        intake=intake,
        issue=issue,
        source=SourceType.PORTAL,
        source_email=EMAIL,
        extra={"requester_name": "Maria"},
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
    body = {"budget_id": str(budget_id)} if budget_id else {}
    if reason:
        body["reason"] = reason
    return APIClient().post(url, body, format="json", HTTP_X_PORTAL_TOKEN=token)


def team_url(workspace, setup, suffix=""):
    return (
        f"/api/workspaces/{workspace.slug}/projects/{setup['project'].id}/issues/{setup['issue'].id}/"
        f"portal-budget/{suffix}"
    )


def cancel(client, workspace, setup, **body):
    return client.post(team_url(workspace, setup, "cancel/"), body, format="json")


def portal_ticket(setup):
    portal = setup["portal"]
    token = create_session(EMAIL, portal.workspace_id, portal.project_id)
    url = f"/api/public/intake-portal/{portal.anchor}/tickets/{setup['issue'].id}/"
    return APIClient().get(url, HTTP_X_PORTAL_TOKEN=token).json()


@pytest.mark.contract
class TestCancelEstimate:
    def test_cancel_pending(self, setup, session_client, workspace, create_user, quiet):
        budget = send(setup, "8", "Duas telas")
        response = cancel(session_client, workspace, setup, budget_id=str(budget.id), reason="Escopo mudou")
        assert response.status_code == 200, response.content
        data = response.json()
        assert data["status"] == "CANCELLED" and data["is_cancelled"] is True and data["can_cancel"] is False
        assert data["cancellation_reason"] == "Escopo mudou" and data["cancelled_at"]
        assert data["can_edit"] is False

        budget.refresh_from_db()
        assert budget.status == "CANCELLED" and budget.cancelled_by_id == create_user.id
        assert [e.kind for e in budget.events.order_by("occurred_at")] == ["sent", "cancelled"]
        assert budget.events.get(kind="cancelled").reason == "Escopo mudou"

        # the client is told by e-mail and the work item history shows it (comment the client also sees)
        quiet["cancel_mail"].assert_called_once_with(str(setup["issue"].id), budget_id=str(budget.id))
        comment = IssueComment.objects.get(issue=setup["issue"])
        assert comment.access == "EXTERNAL" and comment.actor_id == create_user.id
        assert "cancelado pela equipe" in comment.comment_html and "Escopo mudou" in comment.comment_html
        activity = quiet["activity"].call_args.kwargs
        assert activity["type"] == "comment.activity.created" and activity["actor_id"] is None

        # the team sees who cancelled; the client sees "Equipe"
        team = session_client.get(team_url(workspace, setup)).json()
        assert team["budget"]["status"] == "CANCELLED" and team["budget"]["cancelled_by"] != "Equipe"
        client_view = portal_ticket(setup)
        assert client_view["budget"]["is_cancelled"] is True and client_view["budget"]["cancelled_by"] == "Equipe"

    def test_cancel_without_budget_id_takes_the_pending_one(self, setup, session_client, workspace):
        budget = send(setup, "8")
        assert cancel(session_client, workspace, setup).status_code == 200
        budget.refresh_from_db()
        assert budget.status == "CANCELLED" and budget.cancellation_reason == ""

    def test_cancel_rejected(self, setup, session_client, workspace, quiet):
        budget = send(setup, "8")
        assert answer(setup, "reject", reason="Caro").status_code == 200
        response = cancel(session_client, workspace, setup, budget_id=str(budget.id))
        assert response.status_code == 200, response.content
        budget.refresh_from_db()
        assert budget.status == "CANCELLED"
        # the client's rejection stays recorded
        assert budget.rejected_by_email == EMAIL and budget.rejection_reason == "Caro"
        assert [e.kind for e in budget.events.order_by("occurred_at")] == ["sent", "rejected", "cancelled"]
        quiet["cancel_mail"].assert_called_once()

    def test_cancel_approved_is_refused(self, setup, session_client, workspace, quiet):
        budget = send(setup, "8")
        assert answer(setup, "approve").status_code == 200
        assert billing.balance(setup["contract"]) == D("12")

        response = cancel(session_client, workspace, setup, budget_id=str(budget.id))
        assert response.status_code == 400
        assert "estorno" in response.json()["error"]
        budget.refresh_from_db()
        assert budget.status == "APPROVED" and budget.cancelled_at is None
        assert billing.balance(setup["contract"]) == D("12")
        quiet["cancel_mail"].assert_not_called()

    def test_cancel_twice_is_refused(self, setup, session_client, workspace):
        budget = send(setup, "8")
        assert cancel(session_client, workspace, setup, budget_id=str(budget.id)).status_code == 200
        response = cancel(session_client, workspace, setup, budget_id=str(budget.id))
        assert response.status_code == 400 and "já foi cancelado" in response.json()["error"]

    def test_portal_cannot_approve_or_reject_a_cancelled_estimate(self, setup, session_client, workspace):
        budget = send(setup, "8")
        assert cancel(session_client, workspace, setup).status_code == 200

        # the link from the e-mail (no budget id) and an open page (with the id) both fail
        for budget_id in (None, budget.id):
            approve = answer(setup, "approve", budget_id=budget_id)
            assert approve.status_code == 400 and "cancelado" in approve.json()["error"]
            reject = answer(setup, "reject", budget_id=budget_id)
            assert reject.status_code == 400 and "cancelado" in reject.json()["error"]

        budget.refresh_from_db()
        assert budget.status == "CANCELLED" and budget.approved_at is None
        # nothing is debited
        assert not HourLedgerEntry.objects.filter(issue_id=setup["issue"].id, kind="debit").exists()
        assert billing.balance(setup["contract"]) == D("20")

    def test_new_estimate_after_cancel(self, setup, session_client, workspace, quiet):
        first = send(setup, "8")
        assert cancel(session_client, workspace, setup).status_code == 200

        response = session_client.post(
            team_url(workspace, setup), {"estimated_hours": 6, "note": "novo"}, format="json"
        )
        assert response.status_code == 200, response.content
        second = IntakePortalBudget.objects.get(pk=response.json()["id"])
        assert second.id != first.id and second.status == "PENDING"
        statuses = list(
            IntakePortalBudget.objects.filter(issue=setup["issue"])
            .order_by("created_at")
            .values_list("status", flat=True)
        )
        assert statuses == ["CANCELLED", "PENDING"]

        # the new one is answered normally and only it is debited
        assert answer(setup, "approve").status_code == 200
        debits = HourLedgerEntry.objects.filter(issue_id=setup["issue"].id, kind="debit")
        assert [(d.budget_id, d.hours) for d in debits] == [(second.id, D("-6"))]

    def test_cancelled_estimate_is_never_debited(self, setup, session_client, workspace):
        send(setup, "8")
        assert cancel(session_client, workspace, setup).status_code == 200
        # the flows that (re)debit approved estimates ignore it (e.g. the work kind changing back to evolution)
        billing.refresh_contract(setup["contract"])
        assert not billing.approved_budgets(setup["issue"]).exists()
        assert not HourLedgerEntry.objects.filter(issue_id=setup["issue"].id, kind="debit").exists()

        # the time widget no longer counts the cancelled hours as budgeted
        time = session_client.get(
            f"/api/workspaces/{workspace.slug}/projects/{setup['project'].id}/issues/{setup['issue'].id}/time/"
        ).json()
        assert time["budget"] is None

    def test_guest_cannot_cancel(self, setup, workspace):
        guest = User.objects.create(email="convidado@conjo.com.br", username="convidado")
        WorkspaceMember.objects.create(workspace=workspace, member=guest, role=5)
        ProjectMember.objects.create(project=setup["project"], member=guest, role=5, is_active=True)
        budget = send(setup, "8")
        client = APIClient()
        client.force_authenticate(user=guest)
        assert cancel(client, workspace, setup).status_code == 403
        budget.refresh_from_db()
        assert budget.status == "PENDING"

    def test_not_a_portal_ticket(self, setup, session_client, workspace):
        IntakeIssue.objects.filter(pk=setup["ticket"].pk).update(source=SourceType.IN_APP)
        response = cancel(session_client, workspace, setup)
        assert response.status_code == 400 and "portal" in response.json()["error"]

    def test_cancel_e_mail(self, setup, session_client, workspace):
        from plane.bgtasks.intake_portal_task import send_portal_budget_cancelled

        budget = send(setup, "8")
        assert cancel(session_client, workspace, setup, reason="Vamos rever <b>tudo</b>").status_code == 200
        with mock.patch("plane.bgtasks.intake_portal_task.send_transactional_email") as mail:
            send_portal_budget_cancelled(str(setup["issue"].id), budget_id=str(budget.id))
        to, subject, html = mail.call_args.args
        assert to == EMAIL and subject == "Orçamento cancelado: Pedido"
        assert "8 horas" in html and "&lt;b&gt;tudo&lt;/b&gt;" in html and "não pode mais ser aprovado" in html

        # a pending estimate is never announced as cancelled
        other = send(setup, "3")
        with mock.patch("plane.bgtasks.intake_portal_task.send_transactional_email") as mail:
            send_portal_budget_cancelled(str(setup["issue"].id), budget_id=str(other.id))
        mail.assert_not_called()


@pytest.fixture
def mcp(db):
    server = MCPServer.objects.create(is_enabled=True)
    api = APIClient()

    def result(tool, arguments):
        response = api.post(
            "/api/mcp/server/",
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": arguments}},
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {server.token}",
        )
        assert response.status_code == 200, response.content
        return response.json()["result"]

    def call(tool, **arguments):
        data = result(tool, arguments)
        text = data["content"][0]["text"]
        if data["isError"]:
            raise AssertionError(f"{tool} failed: {text}")
        return json.loads(text)

    def fails(tool, **arguments):
        data = result(tool, arguments)
        assert data["isError"], f"{tool} should have failed"
        return data["content"][0]["text"]

    call.fails = fails
    return call


@pytest.mark.contract
class TestCancelEstimateMCP:
    def test_cancel_and_get(self, setup, workspace, mcp, quiet):
        ident = f"CAN-{setup['issue'].sequence_id}"
        args = {"workspace_slug": workspace.slug, "work_item": ident}
        assert "Não há orçamento" in mcp.fails("cancel_hours_estimate", **args)

        sent = mcp("send_hours_estimate", **args, hours=8)
        assert mcp("get_hours_estimate", **args)["estimate"]["can_cancel"] is True

        cancelled = mcp("cancel_hours_estimate", **args, reason="Cliente desistiu")
        assert cancelled["estimate"]["id"] == sent["estimate"]["id"]
        assert cancelled["estimate"]["status"] == "CANCELLED" and cancelled["notified"] == EMAIL
        assert cancelled["estimate"]["cancelled_by"] == "Assistente (MCP)"
        quiet["cancel_mail"].assert_called_once_with(str(setup["issue"].id), budget_id=sent["estimate"]["id"])

        estimate = mcp("get_hours_estimate", **args)
        assert estimate["estimate"]["status"] == "CANCELLED"
        assert estimate["estimate"]["cancellation_reason"] == "Cliente desistiu"
        assert [e["kind"] for e in estimate["estimate"]["events"]] == ["sent", "cancelled"]
        assert estimate["approved_hours"] == 0
        assert "já foi cancelado" in mcp.fails("cancel_hours_estimate", **args)

        # a new one can be sent; list_intake_items shows its status
        again = mcp("send_hours_estimate", **args, hours=5)
        assert again["estimate"]["status"] == "PENDING" and again["estimate"]["id"] != sent["estimate"]["id"]
        assert [e["status"] for e in mcp("get_hours_estimate", **args)["estimates"]] == ["CANCELLED", "PENDING"]

    def test_cancel_rejected_and_refuse_approved(self, setup, workspace, mcp):
        ident = f"CAN-{setup['issue'].sequence_id}"
        args = {"workspace_slug": workspace.slug, "work_item": ident}
        mcp("send_hours_estimate", **args, hours=8)
        assert answer(setup, "reject").status_code == 200
        assert mcp("cancel_hours_estimate", **args)["estimate"]["status"] == "CANCELLED"

        mcp("send_hours_estimate", **args, hours=4)
        assert answer(setup, "approve").status_code == 200
        error = mcp.fails("cancel_hours_estimate", **args)
        assert "aprovado não pode ser cancelado" in error and "estorno" in error
        assert IntakePortalBudget.objects.filter(issue=setup["issue"], status="APPROVED").count() == 1

    def test_not_a_portal_ticket(self, setup, workspace, mcp):
        IntakeIssue.objects.filter(pk=setup["ticket"].pk).update(source=SourceType.IN_APP)
        ident = f"CAN-{setup['issue'].sequence_id}"
        assert "portal" in mcp.fails("cancel_hours_estimate", workspace_slug=workspace.slug, work_item=ident)
