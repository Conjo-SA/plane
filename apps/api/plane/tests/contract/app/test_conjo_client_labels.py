# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""The client is a field of the work item; on shared boards (like MAN) the client's label follows it."""

import importlib
from decimal import Decimal
from unittest import mock

import pytest
from django.apps import apps as django_apps
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
    IntakePortal,
    IntakePortalBudget,
    Issue,
    IssueClient,
    IssueLabel,
    Label,
    Project,
    ProjectMember,
    State,
    User,
    WorkspaceMember,
)
from plane.db.models.intake import SourceType
from plane.space.views.portal_auth import create_session
from plane.utils import conjo_billing as billing

D = Decimal


@pytest.fixture(autouse=True)
def quiet():
    with mock.patch("plane.bgtasks.conjo_billing_task.notify_low_balance.delay"):
        yield


@pytest.fixture
def board(db, workspace, create_user):
    """MAN: one board for every client; RastroPOP and LTQ have packages and a board label each."""
    man = Project.objects.create(name="Manutenção", identifier="MAN", workspace=workspace, created_by=create_user)
    ProjectMember.objects.create(project=man, member=create_user, role=20, is_active=True)
    State.objects.create(name="A fazer", group="unstarted", project=man, workspace=workspace, default=True)
    labels = {
        name: Label.objects.create(name=name, project=man, workspace=workspace)
        for name in ("RastroPOP", "LTQ", "ConjoChat")
    }
    clients = {name: Client.objects.create(workspace=workspace, name=name) for name in ("RastroPOP", "LTQ")}
    for name, client in clients.items():
        ClientLabel.objects.create(workspace=workspace, client=client, label=labels[name])
    ClientContact.objects.create(
        workspace=workspace, client=clients["RastroPOP"], name="Ana", email="ana@rastro.com", can_approve=True
    )
    ClientContact.objects.create(
        workspace=workspace, client=clients["LTQ"], name="Leo", email="leo@ltq.com", can_approve=True
    )
    contracts = {}
    for name, client in clients.items():
        contracts[name] = ClientContract.objects.create(
            workspace=workspace,
            client=client,
            name="Pacote 20h",
            hours_per_month=D("20"),
            starts_on=billing.month_start(billing.today()),
        )
        billing.refresh_contract(contracts[name])
    return {"man": man, "labels": labels, "clients": clients, "contracts": contracts}


def card(board, name, approved_hours=None):
    issue = Issue.objects.create(name=name, project=board["man"])
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


def labels_of(issue):
    return set(IssueLabel.objects.filter(issue=issue).values_list("label__name", flat=True))


def tag(board, issue, name):
    IssueLabel.objects.create(issue=issue, label=board["labels"][name], project=board["man"])
    resync_client_after_label_change(issue.id)


@pytest.mark.contract
class TestCardClient:
    def test_card_client_wins_over_the_project(self, board, workspace):
        owner = Client.objects.create(workspace=workspace, name="Dono do projeto")
        ClientProject.objects.create(workspace=workspace, client=owner, project=board["man"])
        plain = card(board, "Sem cliente no card")
        chosen = card(board, "Com cliente")
        billing.set_issue_client(chosen, board["clients"]["LTQ"])
        assert billing.client_resolution(plain) == (owner, "project")
        assert billing.client_resolution(chosen) == (board["clients"]["LTQ"], "card")
        assert chosen.id in set(billing.client_issues(board["clients"]["LTQ"]).values_list("id", flat=True))
        assert chosen.id not in set(billing.client_issues(owner).values_list("id", flat=True))

    def test_choosing_the_client_applies_its_label_and_debits_its_package(self, board):
        issue = card(board, "Nova tela", approved_hours="8")
        billing.set_issue_client(issue, board["clients"]["RastroPOP"])
        assert labels_of(issue) == {"RastroPOP"}
        assert billing.balance(board["contracts"]["RastroPOP"]) == D("12")

    def test_changing_or_clearing_the_client_moves_the_hours(self, board):
        issue = card(board, "Nova tela", approved_hours="8")
        billing.set_issue_client(issue, board["clients"]["RastroPOP"])
        billing.set_issue_client(issue, board["clients"]["LTQ"])
        assert billing.balance(board["contracts"]["RastroPOP"]) == D("20")
        assert billing.balance(board["contracts"]["LTQ"]) == D("12")
        assert labels_of(issue) == {"LTQ"}
        billing.set_issue_client(issue, None)
        assert billing.balance(board["contracts"]["LTQ"]) == D("20")
        assert billing.client_for_issue(issue) is None and labels_of(issue) == set()
        # Tagging something else afterwards does not bring a client back.
        tag(board, issue, "ConjoChat")
        assert billing.client_for_issue(issue) is None
        # The client can be chosen again after being cleared (soft-deleted links do not block it).
        billing.set_issue_client(issue, board["clients"]["RastroPOP"])
        assert billing.client_for_issue(issue) == board["clients"]["RastroPOP"]
        assert billing.balance(board["contracts"]["RastroPOP"]) == D("12")

    def test_tagging_sets_the_client_only_when_the_card_has_none(self, board):
        issue = card(board, "Bug")
        tag(board, issue, "LTQ")
        assert billing.client_resolution(issue) == (board["clients"]["LTQ"], "card")
        # The client chosen on the card is not overridden by another client's label.
        tag(board, issue, "RastroPOP")
        assert billing.client_for_issue(issue) == board["clients"]["LTQ"]
        both = card(board, "Duas etiquetas")
        IssueLabel.objects.create(issue=both, label=board["labels"]["LTQ"], project=board["man"])
        tag(board, both, "RastroPOP")
        assert billing.client_for_issue(both) is None
        internal = card(board, "Chat interno")
        tag(board, internal, "ConjoChat")
        assert billing.client_for_issue(internal) is None

    def test_linking_a_label_adopts_the_cards_already_tagged(self, board, workspace, session_client):
        new_client = Client.objects.create(workspace=workspace, name="Bridges")
        bridges = Label.objects.create(name="Bridges", project=board["man"], workspace=workspace)
        old = [card(board, f"Antigo {n}") for n in range(3)]
        for issue in old:
            IssueLabel.objects.create(issue=issue, label=bridges, project=board["man"])
        mixed = card(board, "Bridges e LTQ")
        IssueLabel.objects.create(issue=mixed, label=bridges, project=board["man"])
        IssueLabel.objects.create(issue=mixed, label=board["labels"]["LTQ"], project=board["man"])
        response = session_client.put(
            f"/api/workspaces/{workspace.slug}/clients/{new_client.id}/labels/",
            {"label_ids": [str(bridges.id)]},
            format="json",
        )
        assert response.status_code == 200
        assert all(billing.client_for_issue(issue) == new_client for issue in old)
        assert billing.client_for_issue(mixed) is None

    def test_existing_tagged_cards_get_their_client_on_migration(self, board):
        tagged = card(board, "Já tinha etiqueta")
        IssueLabel.objects.create(issue=tagged, label=board["labels"]["RastroPOP"], project=board["man"])
        migration = importlib.import_module("plane.db.migrations.0134_conjo_issue_clients")
        migration.clients_from_labels(django_apps, None)
        assert IssueClient.objects.get(issue=tagged).client == board["clients"]["RastroPOP"]


@pytest.mark.contract
class TestPortal:
    def submit(self, board, workspace, email, tag=None):
        intake = Intake.objects.get_or_create(name="Entrada", project=board["man"], workspace=workspace)[0]
        portal = IntakePortal.objects.get_or_create(
            project=board["man"], defaults={"workspace": workspace, "intake": intake, "is_enabled": True}
        )[0]
        token = create_session(email, workspace.id, board["man"].id)
        payload = {"name": "Erro no login", "requester_email": email, "description_html": "<p>x</p>"}
        if tag:
            payload["tag"] = tag
        with mock.patch("plane.space.views.intake_portal.issue_activity.delay"):
            response = APIClient().post(
                f"/api/public/intake-portal/{portal.anchor}/work-items/",
                payload,
                format="json",
                HTTP_X_PORTAL_TOKEN=token,
            )
        assert response.status_code in (200, 201), response.content
        return IntakeIssue.objects.filter(source=SourceType.PORTAL, source_email=email).latest("created_at").issue

    def test_tag_link_and_registered_contacts_set_the_client(self, board, workspace):
        by_contact = self.submit(board, workspace, "ana@rastro.com")
        assert billing.client_resolution(by_contact) == (board["clients"]["RastroPOP"], "card")
        assert labels_of(by_contact) == {"RastroPOP"}
        by_tag = self.submit(board, workspace, "alguem@ltq.com", tag="LTQ")
        assert billing.client_for_issue(by_tag) == board["clients"]["LTQ"]
        stranger = self.submit(board, workspace, "estranho@gmail.com")
        assert billing.client_for_issue(stranger) is None and labels_of(stranger) == set()

    def test_package_and_approval_follow_the_card_client(self, board):
        issue = card(board, "Pedido")
        billing.set_issue_client(issue, board["clients"]["RastroPOP"])
        assert billing.portal_package(board["man"].id, "ana@rastro.com")["client_name"] == "RastroPOP"
        assert billing.can_approve_estimate(issue, "ana@rastro.com")
        assert not billing.can_approve_estimate(issue, "leo@ltq.com")


@pytest.mark.contract
class TestEndpointsAndMCP:
    def test_issue_client_endpoint(self, board, workspace, session_client):
        issue = card(board, "Tela")
        url = f"/api/workspaces/{workspace.slug}/projects/{board['man'].id}/issues/{issue.id}/client/"
        assert session_client.get(url).json() == {"client": None, "project_client": None, "can_change": True}
        rastro = board["clients"]["RastroPOP"]
        data = session_client.put(url, {"client_id": str(rastro.id)}, format="json").json()
        assert data["client"] == {"id": str(rastro.id), "name": "RastroPOP", "via": "card"}
        assert labels_of(issue) == {"RastroPOP"}
        summary = session_client.get(
            f"/api/workspaces/{workspace.slug}/projects/{board['man'].id}/client-summary/"
        ).json()
        assert summary["issues"] == {str(issue.id): {"id": str(rastro.id), "name": "RastroPOP"}}
        options = session_client.get(f"/api/workspaces/{workspace.slug}/clients/options/").json()["clients"]
        assert [option["name"] for option in options] == ["LTQ", "RastroPOP"]
        assert session_client.put(url, {"client_id": None}, format="json").json()["client"] is None

    def test_members_cannot_move_debited_hours(self, board, workspace):
        issue = card(board, "Aprovado", approved_hours="5")
        billing.set_issue_client(issue, board["clients"]["RastroPOP"])
        member = User.objects.create(email="m@conjo.local", username="m")
        WorkspaceMember.objects.create(workspace=workspace, member=member, role=15)
        ProjectMember.objects.create(project=board["man"], member=member, role=15, is_active=True)
        api = APIClient()
        api.force_authenticate(user=member)
        url = f"/api/workspaces/{workspace.slug}/projects/{board['man'].id}/issues/{issue.id}/client/"
        assert api.get(url).json()["can_change"] is False
        response = api.put(url, {"client_id": str(board["clients"]["LTQ"].id)}, format="json")
        assert response.status_code == 403
        assert billing.balance(board["contracts"]["RastroPOP"]) == D("15")

    def test_mcp_tools(self, board, workspace):
        from plane.mcp.tools import clients as mcp_clients
        from plane.mcp.tools import handlers

        created = handlers.create_work_item(workspace.slug, "MAN", "Relatório", client="LTQ")
        assert labels_of(Issue.objects.get(pk=created["id"])) == {"LTQ"}
        other = handlers.create_work_item(workspace.slug, "MAN", "Outra")
        moved = mcp_clients.set_work_item_client(workspace.slug, other["identifier"], "RastroPOP")
        assert moved["client"]["name"] == "RastroPOP"
        assert handlers.retrieve_work_item(workspace.slug, created["identifier"])["client"]["via"] == "card"
        listed = handlers.list_work_items(workspace.slug, project="MAN", client="RastroPOP")
        assert [item["name"] for item in listed["work_items"]] == ["Outra"]
