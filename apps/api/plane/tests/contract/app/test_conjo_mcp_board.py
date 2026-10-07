# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""MCP: managing the whole board, time, clients and hour packages through the JSON-RPC endpoint."""

import datetime
import json
from decimal import Decimal
from unittest import mock

import pytest
from rest_framework.test import APIClient

from plane.db.models import (
    Client,
    ClientContact,
    ClientProject,
    Cycle,
    CycleIssue,
    Intake,
    IntakeIssue,
    IntakePortalBudget,
    Issue,
    IssueRelation,
    IssueWorkLog,
    Module,
    Project,
    ProjectMember,
    State,
    User,
    WorkspaceMember,
)
from plane.db.models.intake import SourceType
from plane.mcp.models import MCPServer
from plane.mcp.tools.registry import TOOL_REGISTRY
from plane.utils import conjo_billing as billing

D = Decimal


@pytest.fixture(autouse=True)
def quiet_tasks():
    with (
        mock.patch("plane.bgtasks.issue_activities_task.issue_activity.delay") as activity,
        mock.patch("plane.bgtasks.conjo_billing_task.notify_low_balance.delay"),
    ):
        yield activity


@pytest.fixture
def mcp(db):
    server = MCPServer.objects.create(is_enabled=True)
    api = APIClient()

    def call(tool, **arguments):
        response = api.post(
            "/api/mcp/server/",
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": arguments}},
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {server.token}",
        )
        assert response.status_code == 200, response.content
        result = response.json()["result"]
        text = result["content"][0]["text"]
        if result["isError"]:
            raise AssertionError(f"{tool} failed: {text}")
        return json.loads(text)

    def fails(tool, **arguments):
        response = api.post(
            "/api/mcp/server/",
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": arguments}},
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {server.token}",
        )
        result = response.json()["result"]
        assert result["isError"], f"{tool} should have failed"
        return result["content"][0]["text"]

    call.fails = fails
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


@pytest.mark.contract
class TestMCPEndpoint:
    def test_token_is_required(self, mcp):
        response = APIClient().post(
            "/api/mcp/server/",
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            format="json",
            HTTP_AUTHORIZATION="Bearer x",
        )
        assert response.status_code == 401

    def test_disabled_tools_are_refused(self, mcp, workspace, project):
        mcp.server.disabled_tools = ["adjust_client_hours"]
        mcp.server.save()
        assert "desativada" in mcp.fails("adjust_client_hours", **ws(workspace), client="x", hours="1", note="x")


@pytest.mark.contract
class TestBoard:
    def test_full_work_item_lifecycle(self, mcp, workspace, project, quiet_tasks):
        parent = mcp("create_work_item", **ws(workspace), project="FRT", name="Relatórios")
        child = mcp("create_work_item", **ws(workspace), project="FRT", name="Por região", parent=parent["identifier"])
        assert child["parent_id"] == parent["id"]
        assert [
            i["identifier"] for i in mcp("list_sub_work_items", **ws(workspace), work_item="FRT-1")["sub_work_items"]
        ] == ["FRT-2"]
        # A parent cannot become the child of its own child.
        assert "parent" in mcp.fails("update_work_item", **ws(workspace), work_item="FRT-1", parent="FRT-2")

        mcp(
            "add_work_item_relation",
            **ws(workspace),
            work_item="FRT-1",
            relation_type="blocking",
            related_work_item="FRT-2",
        )
        assert (
            mcp("list_work_item_relations", **ws(workspace), work_item="FRT-2")["relations"][0]["relation_type"]
            == "blocked_by"
        )
        assert IssueRelation.objects.count() == 1
        mcp("remove_work_item_relation", **ws(workspace), work_item="FRT-2", related_work_item="FRT-1")
        assert IssueRelation.objects.count() == 0

        link = mcp(
            "add_work_item_link", **ws(workspace), work_item="FRT-1", url="https://example.com/spec", title="Spec"
        )
        assert "http" in mcp.fails("add_work_item_link", **ws(workspace), work_item="FRT-1", url="javascript:alert(1)")
        mcp("delete_work_item_link", **ws(workspace), work_item="FRT-1", link_id=link["id"])

        comment = mcp("add_work_item_comment", **ws(workspace), work_item="FRT-1", comment_html="<p>v1</p>")
        mcp(
            "update_work_item_comment",
            **ws(workspace),
            work_item="FRT-1",
            comment_id=comment["id"],
            comment_html="<p>v2</p>",
        )
        assert (
            mcp("list_work_item_comments", **ws(workspace), work_item="FRT-1")["comments"][0]["comment_html"]
            == "<p>v2</p>"
        )

        detail = mcp("retrieve_work_item", **ws(workspace), work_item="FRT-1")
        assert detail["sub_work_items"] == ["FRT-2"] and detail["state"]["group"] == "unstarted"

        # Archiving follows the app's rule: only finished items.
        assert "concluído ou cancelado" in mcp.fails("archive_work_item", **ws(workspace), work_item="FRT-2")
        done = State.objects.get(project=project, group="completed")
        mcp("update_work_item", **ws(workspace), work_item="FRT-2", state_id=str(done.id))
        mcp("archive_work_item", **ws(workspace), work_item="FRT-2")
        assert mcp("list_work_items", **ws(workspace), project="FRT")["total"] == 1
        assert mcp("list_work_items", **ws(workspace), project="FRT", archived=True)["total"] == 1
        mcp("unarchive_work_item", **ws(workspace), work_item="FRT-2")
        mcp("delete_work_item", **ws(workspace), work_item="FRT-2", confirm=True)
        assert not Issue.objects.filter(pk=child["id"]).exists()
        types = {c.kwargs["type"] for c in quiet_tasks.call_args_list}
        assert {"issue_relation.activity.created", "link.activity.created", "issue.activity.deleted"} <= types

    def test_people_comments_are_not_editable_through_mcp(self, mcp, workspace, project, create_user):
        from plane.db.models import IssueComment

        issue = Issue.objects.create(name="X", project=project)
        comment = IssueComment.objects.create(
            issue=issue, project=project, comment_html="<p>meu</p>", actor=create_user
        )
        message = mcp.fails("delete_work_item_comment", **ws(workspace), work_item="FRT-1", comment_id=str(comment.id))
        assert "pelo MCP" in message

    def test_cycles_modules_and_bulk_update(self, mcp, workspace, project):
        for name in ("A", "B", "C"):
            mcp("create_work_item", **ws(workspace), project="FRT", name=name)
        today = datetime.date.today()
        cycle = mcp(
            "create_cycle",
            **ws(workspace),
            project="FRT",
            name="Sprint 1",
            start_date=today.isoformat(),
            end_date=(today + datetime.timedelta(days=14)).isoformat(),
        )
        other = mcp(
            "create_cycle",
            **ws(workspace),
            project="FRT",
            name="Sprint 2",
            start_date=today.isoformat(),
            end_date=(today + datetime.timedelta(days=28)).isoformat(),
        )
        assert (
            mcp(
                "add_work_items_to_cycle",
                **ws(workspace),
                project="FRT",
                cycle_id=cycle["id"],
                work_items=["FRT-1", "FRT-2"],
            )["added"]
            == 2
        )
        # One cycle per work item: adding to another cycle moves it.
        assert (
            mcp("add_work_items_to_cycle", **ws(workspace), project="FRT", cycle_id=other["id"], work_items=["FRT-2"])[
                "moved"
            ]
            == 1
        )
        assert mcp("retrieve_cycle", **ws(workspace), project="FRT", cycle_id=cycle["id"])["progress"]["total"] == 1
        mcp(
            "update_cycle",
            **ws(workspace),
            project="FRT",
            cycle_id=cycle["id"],
            end_date=(today + datetime.timedelta(days=7)).isoformat(),
        )

        module = mcp("create_module", **ws(workspace), project="FRT", name="Relatórios")
        state = mcp("create_state", **ws(workspace), project="FRT", name="Revisão", group="started")
        mcp(
            "bulk_update_work_items",
            **ws(workspace),
            project="FRT",
            work_items=["FRT-1", "FRT-3"],
            state_id=state["id"],
            priority="high",
            module_id=module["id"],
            cycle_id="",
        )
        assert set(Issue.objects.filter(state_id=state["id"]).values_list("sequence_id", flat=True)) == {1, 3}
        assert not CycleIssue.objects.filter(issue__sequence_id=1, issue__project=project).exists()
        assert len(mcp("retrieve_module", **ws(workspace), project="FRT", module_id=module["id"])["work_items"]) == 2
        listed = mcp("list_work_items", **ws(workspace), project="FRT", module_id=module["id"], state_group="started")
        assert listed["total"] == 2

        assert "ainda estão" in mcp.fails("delete_state", **ws(workspace), project="FRT", state_id=state["id"])
        mcp("delete_cycle", **ws(workspace), project="FRT", cycle_id=other["id"], confirm=True)
        mcp("delete_module", **ws(workspace), project="FRT", module_id=module["id"], confirm=True)
        assert not Cycle.objects.filter(pk=other["id"]).exists() and not Module.objects.filter(pk=module["id"]).exists()
        assert Issue.objects.filter(project=project).count() == 3

    def test_states_labels_pages_members_and_project(self, mcp, workspace, project):
        state = mcp("create_state", **ws(workspace), project="FRT", name="Homologação", group="started")
        mcp("update_state", **ws(workspace), project="FRT", state_id=state["id"], default=True)
        project.refresh_from_db()
        assert str(project.default_state_id) == state["id"]
        assert "padrão" in mcp.fails("delete_state", **ws(workspace), project="FRT", state_id=state["id"])

        label = mcp("create_label", **ws(workspace), project="FRT", name="bug")
        mcp("update_label", **ws(workspace), project="FRT", label_id=label["id"], color="#FF0000")
        mcp("delete_label", **ws(workspace), project="FRT", label_id=label["id"], confirm=True)

        page = mcp("create_page", **ws(workspace), project="FRT", name="Arquitetura", description_html="<p>v1</p>")
        mcp("update_page", **ws(workspace), project="FRT", page_id=page["id"], description_html="<p>v2</p>")
        assert (
            mcp("retrieve_page", **ws(workspace), project="FRT", page_id=page["id"])["description_html"] == "<p>v2</p>"
        )

        user = User.objects.create(email="dev@conjo.local", username="dev")
        WorkspaceMember.objects.create(workspace=workspace, member=user, role=15)
        assert "maior" in mcp.fails(
            "add_project_member", **ws(workspace), project="FRT", member="dev@conjo.local", role="admin"
        )
        mcp("add_project_member", **ws(workspace), project="FRT", member="dev@conjo.local", role="member")
        mcp("remove_project_member", **ws(workspace), project="FRT", member="dev@conjo.local", confirm=True)
        assert not ProjectMember.objects.get(project=project, member=user).is_active

        assert (
            mcp("update_project", **ws(workspace), project="FRT", description="Fretes e entregas")["description"]
            == "Fretes e entregas"
        )

    def test_intake_triage(self, mcp, workspace, project):
        triage = State.objects.create(name="Triagem", group="triage", project=project, workspace=workspace)
        intake = Intake.objects.create(name="Entrada", project=project, workspace=workspace)
        issue = Issue.objects.create(name="Pedido do cliente", project=project, state=triage)
        IntakeIssue.objects.create(
            intake=intake,
            issue=issue,
            project=project,
            workspace=workspace,
            source=SourceType.PORTAL,
            source_email="maria@cliente.com.br",
        )
        # Pending requests are not on the board yet.
        assert mcp("list_work_items", **ws(workspace), project="FRT")["total"] == 0
        items = mcp("list_intake_items", **ws(workspace), project="FRT")["intake_items"]
        assert items[0]["requester_email"] == "maria@cliente.com.br"
        result = mcp("triage_intake_item", **ws(workspace), work_item=items[0]["work_item"], action="accept")
        assert result["status"] == "accepted" and result["state_id"] == str(project.default_state_id)
        assert mcp("list_work_items", **ws(workspace), project="FRT")["total"] == 1


@pytest.mark.contract
class TestTimeAndClients:
    def test_time_kind_clients_and_statement(self, mcp, workspace, project, create_user):
        client = mcp("create_client", **ws(workspace), name="Transportadora", document="12.345.678/0001-90")
        mcp("set_client_projects", **ws(workspace), client="Transportadora", projects=["FRT"])
        mcp(
            "add_client_contact",
            **ws(workspace),
            client=client["id"],
            name="Maria",
            email="maria@x.com",
            can_approve=True,
        )
        mcp(
            "update_client_contact",
            **ws(workspace),
            client="12.345.678/0001-90",
            contact="maria@x.com",
            phone="11 9999",
        )
        created = mcp(
            "create_client_contract",
            **ws(workspace),
            client="Transportadora",
            name="Pacote 20h",
            hours_per_month="20",
            accumulation_months=3,
            starts_on=billing.month_start(billing.today()).isoformat(),
            opening_balance="10",
        )
        assert created["package"]["available"] in ("30.00", "30")

        item = mcp("create_work_item", **ws(workspace), project="FRT", name="Relatório")
        logged = mcp(
            "log_work_item_time",
            **ws(workspace),
            work_item=item["identifier"],
            member=create_user.email,
            duration="1h30",
            description="Relatório mensal",
        )
        assert logged["total_minutes"] == 90
        assert "member" in mcp.fails(
            "log_work_item_time",
            **ws(workspace),
            work_item=item["identifier"],
            member="ninguem@x.com",
            duration="1h",
            description="x",
        )
        assert "duration" in mcp.fails(
            "log_work_item_time",
            **ws(workspace),
            work_item=item["identifier"],
            member=create_user.email,
            duration="99h",
            description="x",
        )
        # Manual entries always say what was done: missing, empty or blank description is refused.
        assert "description" in mcp.fails(
            "log_work_item_time", **ws(workspace), work_item=item["identifier"], member=create_user.email, duration="1h"
        )
        for blank in ("", "   "):
            assert "descreva o que foi feito" in mcp.fails(
                "log_work_item_time",
                **ws(workspace),
                work_item=item["identifier"],
                member=create_user.email,
                duration="1h",
                description=blank,
            )
        assert mcp("get_work_item_time", **ws(workspace), work_item=item["identifier"])["total_minutes"] == 90
        entry_id = logged["logged"]["id"]
        assert "descreva o que foi feito" in mcp.fails(
            "update_work_item_time", **ws(workspace), work_item=item["identifier"], entry_id=entry_id, description=" "
        )
        updated = mcp(
            "update_work_item_time", **ws(workspace), work_item=item["identifier"], entry_id=entry_id, duration="1h30"
        )
        assert updated["total_minutes"] == 90
        # An old entry without description only saves when the fix brings one.
        old = IssueWorkLog.objects.create(
            issue_id=item["id"], project=project, member=create_user, minutes=30, logged_on=billing.today()
        )
        assert "descreva o que foi feito" in mcp.fails(
            "update_work_item_time", **ws(workspace), work_item=item["identifier"], entry_id=str(old.id), duration="1h"
        )
        mcp(
            "update_work_item_time",
            **ws(workspace),
            work_item=item["identifier"],
            entry_id=str(old.id),
            duration="1h",
            description="Reunião",
        )
        old.refresh_from_db()
        assert old.minutes == 60 and old.description == "Reunião"
        old.delete()
        assert "description" in TOOL_REGISTRY["log_work_item_time"].input_schema["required"]

        # Approved estimate: setting evolution debits, maintenance gives back.
        issue = Issue.objects.get(pk=item["id"])
        IntakePortalBudget.objects.create(
            issue=issue, project=project, estimated_hours=D("8"), status="APPROVED", approved_by_email="maria@x.com"
        )
        assert mcp("set_work_item_kind", **ws(workspace), work_item=item["identifier"], kind="evolution")[
            "debited_hours"
        ] in ("8.00", "8")
        statement = mcp("get_client_statement", **ws(workspace), client="Transportadora")
        assert statement["package"]["available"] in ("22.00", "22")
        mcp("set_work_item_kind", **ws(workspace), work_item=item["identifier"], kind="maintenance")
        assert mcp("retrieve_client", **ws(workspace), client="Transportadora")["package"]["available"] in (
            "30.00",
            "30",
        )

        assert "note" in mcp.fails("adjust_client_hours", **ws(workspace), client="Transportadora", hours="2", note="")
        assert "insuficiente" in mcp.fails(
            "adjust_client_hours", **ws(workspace), client="Transportadora", hours="-100", note="x"
        )
        summary = mcp(
            "adjust_client_hours", **ws(workspace), client="Transportadora", hours="-2,5", note="Acerto de março"
        )
        assert summary["available"] in ("27.50", "27.5")

        mcp(
            "add_client_note",
            **ws(workspace),
            client="Transportadora",
            kind="meeting",
            body="Alinhamento",
            contacts=["maria@x.com"],
        )
        timeline = mcp("get_client_timeline", **ws(workspace), client="Transportadora", types=["contacts"])
        assert timeline["events"][0]["contacts"] == ["Maria"]

        report = mcp("time_report", **ws(workspace), client="Transportadora", group_by="kind")
        assert report["total_minutes"] == 90 and report["groups"][0]["key"] == "maintenance"

        ended = mcp("update_client_contract", **ws(workspace), client="Transportadora", is_active=False, confirm=True)
        assert ended["contract"]["is_active"] is False
        assert Client.objects.count() == 1 and ClientContact.objects.count() == 1 and ClientProject.objects.count() == 1

    def test_unknown_client_and_cross_workspace(self, mcp, workspace, project, create_user):
        from plane.db.models import Workspace

        other = Workspace.objects.create(name="Outra", slug="outra", owner=create_user)
        Client.objects.create(workspace=other, name="Alheio")
        assert "não existe" in mcp.fails("retrieve_client", **ws(workspace), client="Alheio")
