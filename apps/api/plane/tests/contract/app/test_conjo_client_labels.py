# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""A board shared by several clients (like MAN): the label tells which client a work item is for."""

import datetime
from decimal import Decimal
from unittest import mock

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from plane.bgtasks.issue_activities_task import resync_client_after_label_change
from plane.db.models import (
    Client,
    ClientContact,
    ClientContract,
    ClientLabel,
    ClientProject,
    Intake,
    IntakeIssue,
    IntakePortalBudget,
    Issue,
    IssueLabel,
    Label,
    Project,
    ProjectMember,
    State,
    User,
    WorkspaceMember,
)
from plane.db.models.intake import SourceType
from plane.utils import conjo_billing as billing

D = Decimal


@pytest.fixture(autouse=True)
def quiet():
    with mock.patch("plane.bgtasks.conjo_billing_task.notify_low_balance.delay"):
        yield


@pytest.fixture
def board(db, workspace, create_user):
    """MAN: one project, two clients told apart by label, plus a dedicated project for a third client."""
    man = Project.objects.create(name="Manutenção", identifier="MAN", workspace=workspace, created_by=create_user)
    ProjectMember.objects.create(project=man, member=create_user, role=20, is_active=True)
    State.objects.create(name="A fazer", group="unstarted", project=man, workspace=workspace, default=True)
    rastro_label = Label.objects.create(name="RastroPOP", project=man, workspace=workspace)
    ltq_label = Label.objects.create(name="LTQ", project=man, workspace=workspace)
    internal_label = Label.objects.create(name="ConjoChat", project=man, workspace=workspace)

    rastro = Client.objects.create(workspace=workspace, name="RastroPOP")
    ltq = Client.objects.create(workspace=workspace, name="LTQ")
    ClientLabel.objects.create(workspace=workspace, client=rastro, label=rastro_label)
    ClientLabel.objects.create(workspace=workspace, client=ltq, label=ltq_label)
    ClientContact.objects.create(
        workspace=workspace, client=rastro, name="Ana", email="ana@rastro.com", can_approve=True
    )
    ClientContact.objects.create(workspace=workspace, client=ltq, name="Leo", email="leo@ltq.com", can_approve=True)

    starts = billing.month_start(billing.today())
    contracts = {}
    for client in (rastro, ltq):
        contracts[client.name] = ClientContract.objects.create(
            workspace=workspace, client=client, name="Pacote 20h", hours_per_month=D("20"), starts_on=starts
        )
        billing.refresh_contract(contracts[client.name])
    return {
        "man": man,
        "labels": {"RastroPOP": rastro_label, "LTQ": ltq_label, "ConjoChat": internal_label},
        "clients": {"RastroPOP": rastro, "LTQ": ltq},
        "contracts": contracts,
    }


def card(board, name, *labels, approved_hours=None):
    issue = Issue.objects.create(name=name, project=board["man"])
    for label in labels:
        IssueLabel.objects.create(issue=issue, label=board["labels"][label], project=board["man"])
    if approved_hours:
        IntakePortalBudget.objects.create(
            issue=issue,
            project=board["man"],
            estimated_hours=D(approved_hours),
            status="APPROVED",
            approved_by_email="ana@rastro.com",
            requested_at=timezone.now(),
            approved_at=timezone.now(),
        )
    return issue


@pytest.mark.contract
class TestResolution:
    def test_label_tells_the_client_on_a_shared_board(self, board):
        rastro_card = card(board, "Erro no app", "RastroPOP")
        ltq_card = card(board, "Relatório", "LTQ")
        untagged = card(board, "Sem etiqueta")
        internal = card(board, "Chat interno", "ConjoChat")
        assert billing.client_resolution(rastro_card)[:3] == (board["clients"]["RastroPOP"], "label", "RastroPOP")
        assert billing.client_for_issue(ltq_card) == board["clients"]["LTQ"]
        assert billing.client_for_issue(untagged) is None
        assert billing.client_for_issue(internal) is None
        ids = set(billing.client_issues(board["clients"]["RastroPOP"]).values_list("id", flat=True))
        assert ids == {rastro_card.id}

    def test_label_wins_over_the_project_and_two_clients_are_ambiguous(self, board, workspace):
        other = Client.objects.create(workspace=workspace, name="Dono do projeto")
        ClientProject.objects.create(workspace=workspace, client=other, project=board["man"])
        assert billing.client_for_issue(card(board, "Sem etiqueta")) == other
        assert billing.client_for_issue(card(board, "Com etiqueta", "LTQ")) == board["clients"]["LTQ"]
        both = card(board, "Duas etiquetas", "LTQ", "RastroPOP")
        client, _, _, ambiguous = billing.client_resolution(both)
        assert client is None and ambiguous
        # Consistent with the lists: an ambiguous card belongs to nobody.
        for name in ("LTQ", "RastroPOP"):
            assert both.id not in set(billing.client_issues(board["clients"][name]).values_list("id", flat=True))
        assert both.id not in set(billing.client_issues(other).values_list("id", flat=True))


@pytest.mark.contract
class TestDebits:
    def test_debit_goes_to_the_package_of_the_label(self, board):
        issue = card(board, "Nova tela", "RastroPOP", approved_hours="8")
        billing.debit_for_estimate(issue, D("8"), "ana@rastro.com")
        assert billing.balance(board["contracts"]["RastroPOP"]) == D("12")
        assert billing.balance(board["contracts"]["LTQ"]) == D("20")

    def test_changing_the_label_moves_the_debit(self, board):
        issue = card(board, "Nova tela", "RastroPOP", approved_hours="8")
        billing.debit_for_estimate(issue, D("8"), "ana@rastro.com")
        IssueLabel.objects.filter(issue=issue).delete()
        IssueLabel.objects.create(issue=issue, label=board["labels"]["LTQ"], project=board["man"])
        resync_client_after_label_change(issue.id)
        assert billing.balance(board["contracts"]["RastroPOP"]) == D("20")
        assert billing.balance(board["contracts"]["LTQ"]) == D("12")
        # Running it again changes nothing.
        resync_client_after_label_change(issue.id)
        assert billing.balance(board["contracts"]["LTQ"]) == D("12")

    def test_tagging_an_approved_item_later_debits_it_and_untagging_gives_back(self, board):
        issue = card(board, "Aprovado sem etiqueta", approved_hours="5")
        resync_client_after_label_change(issue.id)
        assert billing.open_debit(issue) is None
        IssueLabel.objects.create(issue=issue, label=board["labels"]["RastroPOP"], project=board["man"])
        resync_client_after_label_change(issue.id)
        assert billing.balance(board["contracts"]["RastroPOP"]) == D("15")
        IssueLabel.objects.filter(issue=issue).delete()
        resync_client_after_label_change(issue.id)
        assert billing.balance(board["contracts"]["RastroPOP"]) == D("20")

    def test_maintenance_never_moves(self, board):
        from plane.db.models import IssueWorkKind

        issue = card(board, "Bug", approved_hours="5")
        IssueWorkKind.objects.create(issue=issue, project=board["man"], kind=IssueWorkKind.MAINTENANCE)
        IssueLabel.objects.create(issue=issue, label=board["labels"]["RastroPOP"], project=board["man"])
        resync_client_after_label_change(issue.id)
        assert billing.balance(board["contracts"]["RastroPOP"]) == D("20")


@pytest.mark.contract
class TestPortal:
    def test_package_and_approval_follow_the_requester_and_the_card(self, board):
        man = board["man"]
        assert billing.portal_package(man.id, "ana@rastro.com")["client_name"] == "RastroPOP"
        assert billing.portal_package(man.id, "leo@ltq.com")["client_name"] == "LTQ"
        assert billing.portal_package(man.id, "estranho@x.com") is None
        rastro_card = card(board, "Pedido", "RastroPOP")
        assert billing.can_approve_estimate(rastro_card, "ana@rastro.com")
        # A contact of another client cannot approve (and debit) RastroPOP's estimate.
        assert not billing.can_approve_estimate(rastro_card, "leo@ltq.com")

    def test_registered_contacts_requests_arrive_tagged(self, board, workspace):
        from plane.db.models import IntakePortal
        from plane.space.views.portal_auth import create_session

        intake = Intake.objects.create(name="Entrada", project=board["man"], workspace=workspace)
        portal = IntakePortal.objects.create(project=board["man"], workspace=workspace, intake=intake, is_enabled=True)
        token = create_session("ana@rastro.com", workspace.id, board["man"].id)
        with (
            mock.patch("plane.space.views.intake_portal.issue_activity.delay"),
            mock.patch("plane.space.views.intake_portal.intake_portal_submission_task", create=True),
        ):
            response = APIClient().post(
                f"/api/public/intake-portal/{portal.anchor}/work-items/",
                {"name": "Erro no login", "requester_email": "ana@rastro.com", "description_html": "<p>x</p>"},
                format="json",
                HTTP_X_PORTAL_TOKEN=token,
            )
        assert response.status_code in (200, 201), response.content
        issue = IntakeIssue.objects.get(source=SourceType.PORTAL, source_email="ana@rastro.com").issue
        assert list(IssueLabel.objects.filter(issue=issue).values_list("label__name", flat=True)) == ["RastroPOP"]


@pytest.mark.contract
class TestEndpointsAndMCP:
    def test_label_endpoints(self, board, workspace, session_client):
        base = f"/api/workspaces/{workspace.slug}/clients"
        options = session_client.get(f"{base}/label-options/").json()["labels"]
        owners = {option["name"]: (option["client"] or {}).get("name") for option in options}
        assert owners == {"RastroPOP": "RastroPOP", "LTQ": "LTQ", "ConjoChat": None}
        rastro = board["clients"]["RastroPOP"]
        taken = session_client.put(
            f"{base}/{rastro.id}/labels/", {"label_ids": [str(board["labels"]["LTQ"].id)]}, format="json"
        )
        assert taken.status_code == 400 and "LTQ" in taken.json()["error"]
        ok = session_client.put(
            f"{base}/{rastro.id}/labels/",
            {"label_ids": [str(board["labels"]["RastroPOP"].id), str(board["labels"]["ConjoChat"].id)]},
            format="json",
        )
        assert ok.status_code == 200 and {label["name"] for label in ok.json()["labels"]} == {"RastroPOP", "ConjoChat"}

        member = User.objects.create(email="m@conjo.local", username="m")
        WorkspaceMember.objects.create(workspace=workspace, member=member, role=15)
        api = APIClient()
        api.force_authenticate(user=member)
        assert api.put(f"{base}/{rastro.id}/labels/", {"label_ids": []}, format="json").status_code == 403

    def test_timeline_and_time_payload(self, board, workspace, session_client):
        rastro_card = card(board, "Nova tela RastroPOP", "RastroPOP", approved_hours="3")
        card(board, "Coisa da LTQ", "LTQ", approved_hours="4")
        rastro = board["clients"]["RastroPOP"]
        events = session_client.get(f"/api/workspaces/{workspace.slug}/clients/{rastro.id}/timeline/").json()["events"]
        keys = {(event.get("issue") or {}).get("key") for event in events}
        assert f"MAN-{rastro_card.sequence_id}" in keys and all("LTQ" not in str(e) for e in events)
        time = session_client.get(
            f"/api/workspaces/{workspace.slug}/projects/{board['man'].id}/issues/{rastro_card.id}/time/"
        ).json()
        assert time["client"] == {"id": str(rastro.id), "name": "RastroPOP", "via": "label", "label": "RastroPOP"}
        assert time["client_ambiguous"] is False

    def test_mcp_tools(self, board, workspace):
        from plane.mcp.tools import clients as mcp_clients
        from plane.mcp.tools import handlers

        card(board, "Tela", "RastroPOP")
        card(board, "Outra", "LTQ")
        result = mcp_clients.set_client_labels(workspace.slug, "LTQ", ["MAN/LTQ", "MAN/ConjoChat"])
        assert {label["name"] for label in result["labels"]} == {"LTQ", "ConjoChat"}
        listed = handlers.list_work_items(workspace.slug, project="MAN", client="RastroPOP")
        assert [item["name"] for item in listed["work_items"]] == ["Tela"]
        # Silences unused import warnings for fixtures used by name only.
        assert datetime.date.today()
