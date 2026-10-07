# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""MCP: security review fixes and the operator features added on top of the board tools."""

import datetime
import json
from unittest import mock

import pytest
from rest_framework.test import APIClient

from plane.db.models import (
    Client,
    ClientContact,
    ClientTimelineNote,
    Cycle,
    Estimate,
    EstimatePoint,
    FileAsset,
    Intake,
    IntakeIssue,
    IntakePortal,
    IntakePortalBudget,
    Issue,
    IssueComment,
    Label,
    Page,
    Project,
    ProjectMember,
    ProjectPage,
    State,
    User,
    Workspace,
    WorkspaceMember,
)
from plane.db.models.intake import SourceType
from plane.mcp.models import MCPServer, MCPToolCallLog


@pytest.fixture(autouse=True)
def quiet_tasks():
    with (
        mock.patch("plane.bgtasks.issue_activities_task.issue_activity.delay") as activity,
        mock.patch("plane.bgtasks.conjo_billing_task.notify_low_balance.delay"),
        mock.patch("plane.bgtasks.intake_portal_task.send_portal_budget_request.delay") as budget_mail,
        mock.patch("plane.bgtasks.intake_portal_task.send_portal_ticket_created.delay") as ticket_mail,
    ):
        yield {"activity": activity, "budget_mail": budget_mail, "ticket_mail": ticket_mail}


@pytest.fixture
def mcp(db):
    server = MCPServer.objects.create(is_enabled=True)
    api = APIClient()

    def raw(payload, token=None):
        return api.post(
            "/api/mcp/server/",
            payload,
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {token or server.token}",
        )

    def result(tool, arguments):
        response = raw(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": arguments}}
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
    call.raw = raw
    call.server = server
    return call


@pytest.fixture
def project(db, workspace, create_user):
    project = Project.objects.create(name="Fretes", identifier="FRT", workspace=workspace, created_by=create_user)
    ProjectMember.objects.create(project=project, member=create_user, role=20, is_active=True)
    todo = State.objects.create(name="A fazer", group="unstarted", project=project, workspace=workspace, default=True)
    State.objects.create(name="Feito", group="completed", project=project, workspace=workspace)
    project.default_state = todo
    project.save()
    return project


def ws(workspace):
    return {"workspace_slug": workspace.slug}


def _member(workspace, project, email, workspace_role=15, project_role=15):
    user = User.objects.create(email=email, username=email.split("@")[0])
    WorkspaceMember.objects.create(workspace=workspace, member=user, role=workspace_role)
    if project_role:
        ProjectMember.objects.create(project=project, member=user, role=project_role, is_active=True)
    return user


def _portal_ticket(workspace, project, name="Pedido do portal", email="maria@cliente.com.br"):
    triage = State.triage_objects.filter(project=project).first() or State.objects.create(
        name="Triagem", group="triage", project=project, workspace=workspace
    )
    intake = Intake.objects.filter(project=project).first() or Intake.objects.create(
        name="Entrada", project=project, workspace=workspace
    )
    issue = Issue.objects.create(name=name, project=project, state=triage)
    IntakeIssue.objects.create(
        intake=intake,
        issue=issue,
        project=project,
        workspace=workspace,
        source=SourceType.PORTAL,
        source_email=email,
        extra={"requester_name": "Maria"},
    )
    return issue


@pytest.mark.contract
class TestEndpointHardening:
    def test_non_ascii_token_is_401_not_500(self, mcp):
        response = mcp.raw({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, token="tóken-é")
        assert response.status_code == 401

    def test_batch_is_capped(self, mcp):
        batch = [{"jsonrpc": "2.0", "id": i, "method": "ping"} for i in range(50)]
        response = mcp.raw(batch)
        assert response.json()["error"]["code"] == -32600

    def test_arguments_are_checked_against_the_schema(self, mcp, workspace, project):
        assert "lista" in mcp.fails(
            "create_work_item", **ws(workspace), project="FRT", name="X", assignee_ids="not-a-list"
        )
        assert "desconhecido" in mcp.fails("list_projects", **ws(workspace), evil=True)
        assert "obrigatório" in mcp.fails("create_work_item", **ws(workspace), project="FRT")
        assert "inteiro" in mcp.fails("list_work_items", **ws(workspace), limit="abc")
        assert "UUID" in mcp.fails("list_work_items", **ws(workspace), state_id="nope")
        assert "limite" in mcp.fails("create_work_item", **ws(workspace), project="FRT", name="x" * 300)
        # null counts as "not informed"
        assert mcp("list_work_items", **ws(workspace), project=None)["total"] == 0

    def test_invalid_ids_never_become_internal_errors(self, mcp, workspace, project):
        message = mcp.fails("update_work_item", **ws(workspace), work_item="FRT-1", state_id="x")
        assert "Erro interno" not in message

    def test_audit_log_is_bounded_and_secret_free(self, mcp, workspace, project):
        mcp(
            "create_work_item",
            **ws(workspace),
            project="FRT",
            name="Grande",
            description_html="<p>" + "a" * 9000 + "</p>",
        )
        log = MCPToolCallLog.objects.filter(tool_name="create_work_item").first()
        assert len(log.arguments["description_html"]) < 2200
        from plane.mcp.server import audit_arguments

        assert audit_arguments({"api_key": "segredo", "nested": {"password": "x"}}) == {
            "api_key": "[omitido]",
            "nested": {"password": "[omitido]"},
        }


@pytest.mark.contract
class TestStoredXSS:
    def test_html_is_sanitized_everywhere(self, mcp, workspace, project):
        evil = '<p>oi</p><script>alert(1)</script><img src="x" onerror="alert(2)"><a href="javascript:alert(3)">x</a>'
        item = mcp("create_work_item", **ws(workspace), project="FRT", name="XSS", description_html=evil)
        stored = Issue.objects.get(pk=item["id"]).description_html
        assert "<script" not in stored and "onerror" not in stored and "javascript:" not in stored

        mcp("update_work_item", **ws(workspace), work_item=item["identifier"], description_html=evil)
        assert "<script" not in Issue.objects.get(pk=item["id"]).description_html

        comment = mcp("add_work_item_comment", **ws(workspace), work_item=item["identifier"], comment_html=evil)
        assert "<script" not in IssueComment.objects.get(pk=comment["id"]).comment_html
        mcp(
            "update_work_item_comment",
            **ws(workspace),
            work_item=item["identifier"],
            comment_id=comment["id"],
            comment_html=evil,
        )
        assert "onerror" not in IssueComment.objects.get(pk=comment["id"]).comment_html

        page = mcp("create_page", **ws(workspace), project="FRT", name="P", description_html=evil)
        assert "<script" not in Page.objects.get(pk=page["id"]).description_html
        mcp("update_page", **ws(workspace), project="FRT", page_id=page["id"], description_html=evil)
        assert "javascript:" not in Page.objects.get(pk=page["id"]).description_html

    def test_colors_and_links_are_validated(self, mcp, workspace, project):
        assert "hexadecimal" in mcp.fails("create_label", **ws(workspace), project="FRT", name="x", color="red;x")
        mcp("create_work_item", **ws(workspace), project="FRT", name="A")
        assert "http" in mcp.fails("add_work_item_link", **ws(workspace), work_item="FRT-1", url="https://")


@pytest.mark.contract
class TestScopingAndRoles:
    def test_guests_and_strangers_cannot_be_assigned(self, mcp, workspace, project):
        guest = _member(workspace, project, "guest@x.com", workspace_role=5, project_role=5)
        outsider = _member(workspace, project, "out@x.com", project_role=None)
        for user in (guest, outsider):
            assert "convidados" in mcp.fails(
                "create_work_item", **ws(workspace), project="FRT", name="X", assignee_ids=[str(user.id)]
            )
        assert Issue.objects.count() == 0

    def test_replaced_assignees_do_not_linger(self, mcp, workspace, project, create_user):
        dev = _member(workspace, project, "dev@x.com")
        item = mcp("create_work_item", **ws(workspace), project="FRT", name="A", assignee_ids=[str(create_user.id)])
        mcp("update_work_item", **ws(workspace), work_item=item["identifier"], assignee_ids=[str(dev.id)])
        listed = mcp("list_work_items", **ws(workspace), project="FRT")["work_items"][0]
        assert listed["assignee_ids"] == [str(dev.id)]

    def test_other_workspace_and_other_project_are_out_of_reach(self, mcp, workspace, project, create_user):
        other_ws = Workspace.objects.create(name="Outra", slug="outra", owner=create_user)
        foreign_project = Project.objects.create(name="Alheio", identifier="ALH", workspace=other_ws)
        foreign = Issue.objects.create(name="Alheio", project=foreign_project)
        sibling = Project.objects.create(name="Irmão", identifier="IRM", workspace=workspace)
        sibling_label = Label.objects.create(name="bug", project=sibling, workspace=workspace)
        item = mcp("create_work_item", **ws(workspace), project="FRT", name="A")

        assert "não existe" in mcp.fails(
            "add_work_item_relation",
            **ws(workspace),
            work_item=item["identifier"],
            relation_type="relates_to",
            related_work_item=str(foreign.id),
        )
        assert "não existe" in mcp.fails("update_work_item", **ws(workspace), work_item=str(foreign.id), name="x")
        assert "projeto" in mcp.fails(
            "update_work_item", **ws(workspace), work_item=item["identifier"], label_ids=[str(sibling_label.id)]
        )

    def test_private_pages_of_people_stay_private(self, mcp, workspace, project, create_user):
        private = Page.objects.create(name="Diário", owned_by=create_user, access=1, workspace=workspace)
        ProjectPage.objects.create(page=private, project=project, workspace=workspace)
        assert mcp("list_pages", **ws(workspace), project="FRT")["pages"] == []
        assert "não existe" in mcp.fails("retrieve_page", **ws(workspace), project="FRT", page_id=str(private.id))
        assert "não existe" in mcp.fails(
            "update_page", **ws(workspace), project="FRT", page_id=str(private.id), name="x"
        )

    def test_project_member_roles_follow_the_app(self, mcp, workspace, project, create_user):
        _member(workspace, project, "boss@x.com", workspace_role=20, project_role=None)
        assert "admin" in mcp.fails(
            "add_project_member", **ws(workspace), project="FRT", member="boss@x.com", role="member"
        )
        # create_user is the only project admin: cannot be demoted nor removed.
        assert "última" in mcp.fails(
            "remove_project_member", **ws(workspace), project="FRT", member=create_user.email, confirm=True
        )


@pytest.mark.contract
class TestConfirmations:
    def test_irreversible_tools_need_confirm(self, mcp, workspace, project):
        today = datetime.date.today()
        cycle = mcp(
            "create_cycle",
            **ws(workspace),
            project="FRT",
            name="S1",
            start_date=today.isoformat(),
            end_date=(today + datetime.timedelta(days=7)).isoformat(),
        )
        assert "confirm=true" in mcp.fails("delete_cycle", **ws(workspace), project="FRT", cycle_id=cycle["id"])
        assert Cycle.objects.filter(pk=cycle["id"]).exists()
        item = mcp("create_work_item", **ws(workspace), project="FRT", name="A")
        assert "confirm=true" in mcp.fails("delete_work_item", **ws(workspace), work_item=item["identifier"])
        assert Issue.objects.filter(pk=item["id"]).exists()

    def test_large_bulk_update_needs_confirm(self, mcp, workspace, project):
        for i in range(21):
            Issue.objects.create(name=f"I{i}", project=project)
        items = [f"FRT-{i}" for i in range(1, 22)]
        assert "confirm=true" in mcp.fails(
            "bulk_update_work_items", **ws(workspace), project="FRT", work_items=items, priority="high"
        )
        mcp("bulk_update_work_items", **ws(workspace), project="FRT", work_items=items, priority="high", confirm=True)
        assert Issue.objects.filter(priority="high").count() == 21


@pytest.mark.contract
class TestClientFacing:
    def test_public_comment_only_where_a_client_reads(self, mcp, workspace, project):
        mcp("create_work_item", **ws(workspace), project="FRT", name="Interno")
        assert "nota interna" in mcp.fails(
            "add_work_item_comment", **ws(workspace), work_item="FRT-1", comment_html="<p>oi</p>", public=True
        )
        ticket = _portal_ticket(workspace, project)
        ident = f"FRT-{ticket.sequence_id}"
        reply = mcp("add_work_item_comment", **ws(workspace), work_item=ident, comment_html="<p>oi</p>", public=True)
        assert reply["access"] == "EXTERNAL" and "maria@cliente.com.br" in reply["visible_to"]
        note = mcp("add_work_item_comment", **ws(workspace), work_item=ident, comment_html="<p>interno</p>")
        assert note["access"] == "INTERNAL"
        comments = mcp("list_work_item_comments", **ws(workspace), work_item=ident)["comments"]
        assert [c["visible_to_client"] for c in comments] == [True, False]

    def test_hours_estimate_goes_to_the_requester(self, mcp, workspace, project, quiet_tasks):
        mcp("create_work_item", **ws(workspace), project="FRT", name="Interno")
        assert "portal" in mcp.fails("send_hours_estimate", **ws(workspace), work_item="FRT-1", hours=4)
        ticket = _portal_ticket(workspace, project)
        ident = f"FRT-{ticket.sequence_id}"
        sent = mcp("send_hours_estimate", **ws(workspace), work_item=ident, hours="6,5", note="Duas telas")
        assert sent["estimate"]["status"] == "PENDING" and sent["estimate"]["estimated_hours"] == 6.5
        quiet_tasks["budget_mail"].assert_called_once_with(str(ticket.id), budget_id=sent["estimate"]["id"])
        assert mcp("get_hours_estimate", **ws(workspace), work_item=ident)["estimate"]["note"] == "Duas telas"

        # after an approval, sending again creates an additional estimate; the approved one never changes
        IntakePortalBudget.objects.filter(issue=ticket).update(status="APPROVED")
        extra = mcp("send_hours_estimate", **ws(workspace), work_item=ident, hours=10)
        assert extra["estimate"]["id"] != sent["estimate"]["id"] and extra["estimate"]["status"] == "PENDING"
        estimate = mcp("get_hours_estimate", **ws(workspace), work_item=ident)
        assert [e["status"] for e in estimate["estimates"]] == ["APPROVED", "PENDING"]
        assert estimate["approved_hours"] == 6.5

    def test_intake_item_on_behalf_of_a_client(self, mcp, workspace, project, quiet_tasks):
        assert "Entrada" in mcp.fails("create_intake_item", **ws(workspace), project="FRT", name="Pedido")
        intake = Intake.objects.create(name="Entrada", project=project, workspace=workspace)
        client = Client.objects.create(workspace=workspace, name="Transportadora")
        created = mcp("create_intake_item", **ws(workspace), project="FRT", name="Pedido", client="Transportadora")
        assert created["source"] == "IN_APP" and created["state"]["group"] == "triage"
        assert mcp("list_work_items", **ws(workspace), project="FRT")["total"] == 0
        assert mcp("list_intake_items", **ws(workspace), project="FRT")["intake_items"][0]["name"] == "Pedido"

        assert "contato" in mcp.fails(
            "create_intake_item",
            **ws(workspace),
            project="FRT",
            name="Pedido 2",
            client="Transportadora",
            requester_email="estranho@x.com",
        )
        ClientContact.objects.create(client=client, workspace=workspace, name="Maria", email="maria@t.com")
        assert "portal" in mcp.fails(
            "create_intake_item",
            **ws(workspace),
            project="FRT",
            name="Pedido 2",
            client="Transportadora",
            requester_email="maria@t.com",
        )
        IntakePortal.objects.create(intake=intake, project=project, workspace=workspace, is_enabled=True)
        ticket = mcp(
            "create_intake_item",
            **ws(workspace),
            project="FRT",
            name="Pedido 2",
            client="Transportadora",
            requester_email="MARIA@t.com",
        )
        assert ticket["source"] == "PORTAL" and ticket["requester_email"] == "maria@t.com"
        quiet_tasks["ticket_mail"].assert_called_once_with(ticket["id"])

    def test_client_notes_only_mcp_authored_can_be_deleted(self, mcp, workspace, project, create_user):
        client = Client.objects.create(workspace=workspace, name="Transportadora")
        human = ClientTimelineNote.objects.create(
            client=client,
            workspace=workspace,
            kind="note",
            body="minha",
            occurred_at=datetime.datetime.now(datetime.timezone.utc),
            created_by=create_user,
        )
        assert "MCP" in mcp.fails("delete_client_note", **ws(workspace), client="Transportadora", note_id=str(human.id))
        mine = mcp("add_client_note", **ws(workspace), client="Transportadora", kind="call", body="Ligação")
        mcp("delete_client_note", **ws(workspace), client="Transportadora", note_id=mine["id"])
        assert not ClientTimelineNote.objects.filter(pk=mine["id"]).exists()

    def test_approver_contact_needs_a_valid_email(self, mcp, workspace, project):
        Client.objects.create(workspace=workspace, name="Transportadora")
        assert "e-mail" in mcp.fails(
            "add_client_contact", **ws(workspace), client="Transportadora", name="Zé", email="nao-e-email"
        )
        assert "e-mail" in mcp.fails(
            "add_client_contact", **ws(workspace), client="Transportadora", name="Zé", can_approve=True
        )


@pytest.mark.contract
class TestOperatorFeatures:
    def test_my_work_filters(self, mcp, workspace, project, create_user):
        today = datetime.date.today()
        mcp(
            "create_work_item",
            **ws(workspace),
            project="FRT",
            name="Atrasado",
            target_date=(today - datetime.timedelta(days=2)).isoformat(),
            assignee_ids=[str(create_user.id)],
        )
        mcp(
            "create_work_item",
            **ws(workspace),
            project="FRT",
            name="Semana que vem",
            target_date=(today + datetime.timedelta(days=7)).isoformat(),
        )
        mine = mcp("list_work_items", **ws(workspace), assignee=create_user.email)
        assert [i["name"] for i in mine["work_items"]] == ["Atrasado"]
        assert mine["work_items"][0]["assignee_emails"] == [create_user.email]
        assert [i["name"] for i in mcp("list_work_items", **ws(workspace), overdue=True)["work_items"]] == ["Atrasado"]
        due = mcp("list_work_items", **ws(workspace), due_before=(today + datetime.timedelta(days=10)).isoformat())
        assert due["total"] == 2
        assert "não é membro" in mcp.fails("list_work_items", **ws(workspace), assignee="ninguem@x.com")

    def test_estimate_points(self, mcp, workspace, project):
        assert mcp("list_estimate_points", **ws(workspace), project="FRT")["points"] == []
        estimate = Estimate.objects.create(name="Pontos", project=project, workspace=workspace, type="points")
        for key, value in enumerate(["1", "3", "5"]):
            EstimatePoint.objects.create(estimate=estimate, key=key, value=value, project=project, workspace=workspace)
        project.estimate = estimate
        project.save()
        item = mcp("create_work_item", **ws(workspace), project="FRT", name="A", estimate_point="3")
        assert Issue.objects.get(pk=item["id"]).estimate_point.value == "3"
        assert "Valores possíveis" in mcp.fails(
            "update_work_item", **ws(workspace), work_item=item["identifier"], estimate_point="8"
        )
        mcp("update_work_item", **ws(workspace), work_item=item["identifier"], estimate_point="")
        assert Issue.objects.get(pk=item["id"]).estimate_point_id is None

    def test_attachments_are_listed_with_signed_download(self, mcp, workspace, project):
        issue = Issue.objects.create(name="Com anexo", project=project)
        FileAsset.objects.create(
            asset="ws/anexo.pdf",
            attributes={"name": "anexo.pdf", "type": "application/pdf"},
            size=1234,
            issue=issue,
            project=project,
            workspace=workspace,
            entity_type=FileAsset.EntityTypeContext.ISSUE_ATTACHMENT,
            is_uploaded=True,
        )
        with mock.patch("plane.settings.storage.S3Storage") as storage:
            storage.return_value.generate_presigned_url.return_value = "https://s3/signed"
            listed = mcp("list_work_item_attachments", **ws(workspace), work_item="FRT-1")
        assert listed["attachments"][0]["name"] == "anexo.pdf"
        assert listed["attachments"][0]["download_url"] == "https://s3/signed"
        kwargs = storage.return_value.generate_presigned_url.call_args.kwargs
        assert kwargs["disposition"] == "attachment" and kwargs["expiration"] == 600

    def test_archive_project_and_server_info(self, mcp, workspace, project):
        assert mcp("archive_project", **ws(workspace), project="FRT")["is_archived"] is True
        assert mcp("unarchive_project", **ws(workspace), project="FRT")["is_archived"] is False
        info = mcp("server_info")
        assert info["enabled_tools"] > 80
        assert "delete_cycle" in info["confirmation_required"]
        assert info["limits"]["max_messages_per_batch"] == 20

    def test_every_tool_is_described_in_portuguese(self):
        from plane.mcp.tools import TOOL_REGISTRY

        english = ("List ", "Create ", "Delete ", "Update ", "Retrieve ")
        for tool in TOOL_REGISTRY.values():
            assert not tool.description.startswith(english), tool.name
            for name, spec in tool.input_schema.get("properties", {}).items():
                assert spec.get("description"), f"{tool.name}.{name} sem descrição"
