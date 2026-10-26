# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Documentação: pages of every project browsed by project and by tag (label), in the app and in the MCP."""

import json
from unittest import mock

import pytest
from rest_framework.test import APIClient

from plane.db.models import (
    Label,
    Page,
    PageLabel,
    Project,
    ProjectMember,
    ProjectPage,
    User,
    Workspace,
    WorkspaceMember,
)
from plane.mcp.models import MCPServer


@pytest.fixture(autouse=True)
def quiet():
    with (
        mock.patch("plane.bgtasks.page_transaction_task.page_transaction.delay"),
        mock.patch("plane.bgtasks.recent_visited_task.recent_visited_task.delay"),
    ):
        yield


def make_page(project, owner, name, access=Page.PUBLIC_ACCESS, labels=()):
    page = Page.objects.create(name=name, workspace=project.workspace, owned_by=owner, access=access)
    ProjectPage.objects.create(page=page, project=project, workspace=project.workspace)
    for label in labels:
        PageLabel.objects.create(page=page, label=label, workspace=project.workspace)
    return page


@pytest.fixture
def docs(db, workspace, create_user):
    """WIKI and MAN, both with the owner; Ana is a member of WIKI only, Gil a guest of WIKI."""
    wiki = Project.objects.create(name="Wiki", identifier="WIKI", workspace=workspace, created_by=create_user)
    man = Project.objects.create(name="Manutenção", identifier="MAN", workspace=workspace, created_by=create_user)
    ana = User.objects.create(email="ana@conjo.local", username="ana")
    gil = User.objects.create(email="gil@conjo.local", username="gil")
    WorkspaceMember.objects.create(workspace=workspace, member=ana, role=15)
    WorkspaceMember.objects.create(workspace=workspace, member=gil, role=5)
    for project in (wiki, man):
        ProjectMember.objects.create(project=project, member=create_user, role=20, is_active=True)
    ProjectMember.objects.create(project=wiki, member=ana, role=15, is_active=True)
    ProjectMember.objects.create(project=wiki, member=gil, role=5, is_active=True)
    pap_man = Label.objects.create(name="PaP", project=man, workspace=workspace)
    pap_wiki = Label.objects.create(name="pap", project=wiki, workspace=workspace)
    rastro = Label.objects.create(name="RastroPOP", project=man, workspace=workspace)
    pages = {
        "deploy": make_page(wiki, create_user, "Deploy", labels=[pap_wiki]),
        "rascunho": make_page(wiki, create_user, "Rascunho", access=Page.PRIVATE_ACCESS),
        "da_ana": make_page(wiki, ana, "Notas da Ana", access=Page.PRIVATE_ACCESS),
        "do_gil": make_page(wiki, gil, "Notas do Gil"),
        "checkout": make_page(man, create_user, "Checkout", labels=[pap_man, rastro]),
    }
    return {
        "wiki": wiki,
        "man": man,
        "ana": ana,
        "gil": gil,
        "labels": {"pap_man": pap_man, "pap_wiki": pap_wiki, "rastro": rastro},
        "pages": pages,
    }


def client_for(user):
    api = APIClient()
    api.force_authenticate(user=user)
    return api


def names(response):
    assert response.status_code == 200, response.content
    return sorted(page["name"] for page in response.json())


@pytest.mark.contract
class TestWorkspacePages:
    url = "/api/workspaces/test-workspace/pages/"

    def test_owner_sees_every_project_and_own_private_pages(self, session_client, docs):
        response = session_client.get(self.url)
        assert names(response) == ["Checkout", "Deploy", "Notas do Gil", "Rascunho"]
        checkout = next(page for page in response.json() if page["name"] == "Checkout")
        assert checkout["project_ids"] == [str(docs["man"].id)]
        assert sorted(checkout["label_ids"]) == sorted(
            [str(docs["labels"]["pap_man"].id), str(docs["labels"]["rastro"].id)]
        )

    def test_member_only_sees_projects_they_belong_to(self, docs):
        # MAN is not Ana's project; the owner's private draft is not hers.
        assert names(client_for(docs["ana"]).get(self.url)) == ["Deploy", "Notas da Ana", "Notas do Gil"]

    def test_guest_only_sees_own_pages_unless_project_allows(self, docs):
        assert names(client_for(docs["gil"]).get(self.url)) == ["Notas do Gil"]
        docs["wiki"].guest_view_all_features = True
        docs["wiki"].save()
        assert names(client_for(docs["gil"]).get(self.url)) == ["Deploy", "Notas do Gil"]

    def test_shared_page_does_not_reveal_other_projects(self, docs):
        ProjectPage.objects.create(
            page=docs["pages"]["checkout"], project=docs["wiki"], workspace=docs["wiki"].workspace
        )
        checkout = next(p for p in client_for(docs["ana"]).get(self.url).json() if p["name"] == "Checkout")
        assert checkout["project_ids"] == [str(docs["wiki"].id)]

    def test_inactive_member_archived_project_and_removed_link(self, session_client, docs):
        ProjectMember.objects.filter(project=docs["wiki"], member=docs["ana"]).update(is_active=False)
        assert names(client_for(docs["ana"]).get(self.url)) == []
        ProjectPage.objects.filter(page=docs["pages"]["checkout"]).delete()
        docs["pages"]["deploy"].archived_at = docs["pages"]["deploy"].created_at
        docs["pages"]["deploy"].save()
        assert names(session_client.get(self.url)) == ["Notas do Gil", "Rascunho"]

    def test_other_workspace_is_refused(self, docs):
        other = Workspace.objects.create(name="Outra", slug="outra", owner=docs["ana"])
        WorkspaceMember.objects.create(workspace=other, member=docs["ana"], role=20)
        assert client_for(docs["ana"]).get("/api/workspaces/outra/pages/").json() == []
        assert client_for(docs["gil"]).get("/api/workspaces/outra/pages/").status_code == 403

    def test_subpages_archived_and_shared_private_pages_of_others(self, docs, create_user):
        wiki, man = docs["wiki"], docs["man"]
        ProjectMember.objects.create(project=man, member=docs["ana"], role=15, is_active=True)
        private = make_page(wiki, create_user, "Privada compartilhada", access=Page.PRIVATE_ACCESS)
        ProjectPage.objects.create(page=private, project=man, workspace=man.workspace)
        child = make_page(wiki, create_user, "Subpágina")
        child.parent = docs["pages"]["deploy"]
        child.save()
        archived = make_page(wiki, create_user, "Arquivada")
        archived.archived_at = archived.created_at
        archived.save()
        assert names(client_for(docs["ana"]).get(self.url)) == ["Checkout", "Deploy", "Notas da Ana", "Notas do Gil"]

    def test_tags_of_projects_the_reader_is_not_in_stay_hidden(self, session_client, docs):
        page = docs["pages"]["deploy"]
        PageLabel.objects.create(page=page, label=docs["labels"]["rastro"], workspace=page.workspace)
        deploy = next(p for p in client_for(docs["ana"]).get(self.url).json() if p["name"] == "Deploy")
        assert deploy["label_ids"] == [str(docs["labels"]["pap_wiki"].id)]
        project_list = client_for(docs["ana"]).get(f"/api/workspaces/test-workspace/projects/{docs['wiki'].id}/pages/")
        listed = next(p for p in project_list.json() if p["name"] == "Deploy")
        assert listed["label_ids"] == [str(docs["labels"]["pap_wiki"].id)]


@pytest.mark.contract
class TestPageLabels:
    def url(self, project, page=None):
        base = f"/api/workspaces/test-workspace/projects/{project.id}/pages/"
        return f"{base}{page.id}/" if page else base

    def test_tags_from_another_project_of_the_workspace(self, session_client, docs):
        page = docs["pages"]["deploy"]
        response = session_client.patch(
            self.url(docs["wiki"], page), {"labels": [str(docs["labels"]["rastro"].id)]}, format="json"
        )
        assert response.status_code == 200, response.content
        listed = next(p for p in session_client.get(self.url(docs["wiki"])).json() if p["name"] == "Deploy")
        # The label removed by the update no longer shows up.
        assert listed["label_ids"] == [str(docs["labels"]["rastro"].id)]

    def test_label_from_another_workspace_is_refused(self, session_client, docs, create_user):
        other = Workspace.objects.create(name="Outra", slug="outra", owner=create_user)
        foreign_project = Project.objects.create(name="X", identifier="X", workspace=other)
        foreign = Label.objects.create(name="Segredo", project=foreign_project, workspace=other)
        page = docs["pages"]["deploy"]
        response = session_client.patch(self.url(docs["wiki"], page), {"labels": [str(foreign.id)]}, format="json")
        assert response.status_code == 400
        response = session_client.post(
            self.url(docs["wiki"]), {"name": "Nova", "labels": [str(foreign.id)]}, format="json"
        )
        assert response.status_code == 400
        assert not PageLabel.objects.filter(label=foreign).exists()

    def test_label_from_a_project_the_author_is_not_in_is_refused(self, docs):
        response = client_for(docs["ana"]).post(
            self.url(docs["wiki"]), {"name": "Nova", "labels": [str(docs["labels"]["rastro"].id)]}, format="json"
        )
        assert response.status_code == 400
        response = client_for(docs["ana"]).post(
            self.url(docs["wiki"]), {"name": "Nova", "labels": [str(docs["labels"]["pap_wiki"].id)]}, format="json"
        )
        assert response.status_code == 201, response.content
        assert response.json()["label_ids"] == [str(docs["labels"]["pap_wiki"].id)]

    def test_hidden_tags_are_kept_when_someone_else_edits_the_tags(self, docs):
        page = docs["pages"]["deploy"]
        PageLabel.objects.create(page=page, label=docs["labels"]["rastro"], workspace=page.workspace)
        # Ana cannot see RastroPOP (MAN): she sends only what she sees and the hidden tag stays.
        response = client_for(docs["ana"]).patch(self.url(docs["wiki"], page), {"labels": []}, format="json")
        assert response.status_code == 200, response.content
        assert list(PageLabel.objects.filter(page=page).values_list("label_id", flat=True)) == [
            docs["labels"]["rastro"].id
        ]

    def test_workspace_label_accepted_archived_project_label_refused(self, session_client, docs, create_user):
        workspace = docs["wiki"].workspace
        global_label = Label.objects.create(name="Geral", project=None, workspace=workspace)
        old = Project.objects.create(name="Antigo", identifier="OLD", workspace=workspace, created_by=create_user)
        ProjectMember.objects.create(project=old, member=create_user, role=20, is_active=True)
        old_label = Label.objects.create(name="Legado", project=old, workspace=workspace)
        old.archived_at = old.created_at
        old.save()
        page = docs["pages"]["deploy"]
        response = session_client.patch(self.url(docs["wiki"], page), {"labels": [str(old_label.id)]}, format="json")
        assert response.status_code == 400
        response = session_client.patch(self.url(docs["wiki"], page), {"labels": [str(global_label.id)]}, format="json")
        assert response.status_code == 200, response.content

    def test_removed_member_cannot_tag_with_their_old_project(self, docs):
        ProjectMember.objects.create(project=docs["man"], member=docs["ana"], role=15, is_active=False)
        page = docs["pages"]["deploy"]
        response = client_for(docs["ana"]).patch(
            self.url(docs["wiki"], page), {"labels": [str(docs["labels"]["rastro"].id)]}, format="json"
        )
        assert response.status_code == 400

    def test_guest_cannot_change_tags(self, docs):
        page = docs["pages"]["deploy"]
        response = client_for(docs["gil"]).patch(self.url(docs["wiki"], page), {"labels": []}, format="json")
        assert response.status_code == 403
        assert PageLabel.objects.filter(page=page).count() == 1


@pytest.fixture
def mcp(db):
    server = MCPServer.objects.create(is_enabled=True)
    api = APIClient()

    def send(tool, arguments):
        response = api.post(
            "/api/mcp/server/",
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": arguments}},
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {server.token}",
        )
        assert response.status_code == 200, response.content
        return response.json()["result"]

    def call(tool, **arguments):
        result = send(tool, arguments)
        assert not result["isError"], result["content"][0]["text"]
        return json.loads(result["content"][0]["text"])

    def fails(tool, **arguments):
        result = send(tool, arguments)
        assert result["isError"], f"{tool} should have failed"
        return result["content"][0]["text"]

    call.fails = fails
    return call


@pytest.mark.contract
class TestMCPDocs:
    def ws(self):
        return {"workspace_slug": "test-workspace"}

    def listed(self, mcp, **filters):
        return sorted(page["name"] for page in mcp("list_pages", **self.ws(), **filters)["pages"])

    def test_list_whole_workspace_without_private_pages_of_people(self, mcp, docs):
        assert self.listed(mcp) == ["Checkout", "Deploy", "Notas do Gil"]
        assert self.listed(mcp, project="MAN") == ["Checkout"]
        assert self.listed(mcp, search="notas") == ["Notas do Gil"]

    def test_tag_is_the_label_name_across_projects(self, mcp, docs):
        assert self.listed(mcp, label="PAP") == ["Checkout", "Deploy"]
        assert self.listed(mcp, label=str(docs["labels"]["pap_wiki"].id)) == ["Checkout", "Deploy"]
        assert self.listed(mcp, label="RastroPOP", project="WIKI") == []
        assert "não existe" in mcp.fails("list_pages", **self.ws(), label="Inexistente")

    def test_archived_project_is_left_out(self, mcp, docs):
        docs["man"].archived_at = docs["man"].created_at
        docs["man"].save()
        assert self.listed(mcp) == ["Deploy", "Notas do Gil"]

    def test_create_and_update_page_tags(self, mcp, docs):
        page = mcp("create_page", **self.ws(), project="WIKI", name="GMUD", labels=["pap", "RastroPOP"])
        # By name, the page's own project label wins.
        assert sorted(label["id"] for label in page["labels"]) == sorted(
            [str(docs["labels"]["pap_wiki"].id), str(docs["labels"]["rastro"].id)]
        )
        assert page["projects"] == ["WIKI"]
        page = mcp("update_page", **self.ws(), project="WIKI", page_id=page["id"], labels=["RastroPOP"])
        assert [label["name"] for label in page["labels"]] == ["RastroPOP"]
        retrieved = mcp("retrieve_page", **self.ws(), project="WIKI", page_id=page["id"])
        assert [label["name"] for label in retrieved["labels"]] == ["RastroPOP"]
        assert self.listed(mcp, label="RastroPOP") == ["Checkout", "GMUD"]

    def test_labels_of_another_workspace_are_refused(self, mcp, docs, create_user):
        other = Workspace.objects.create(name="Outra", slug="outra", owner=create_user)
        foreign_project = Project.objects.create(name="X", identifier="X", workspace=other)
        foreign = Label.objects.create(name="Segredo", project=foreign_project, workspace=other)
        assert "não existe" in mcp.fails(
            "create_page", **self.ws(), project="WIKI", name="Vaza", labels=[str(foreign.id)]
        )
        assert "não existe" in mcp.fails("create_page", **self.ws(), project="WIKI", name="Vaza", labels=["Segredo"])
        assert "não existe" in mcp.fails("list_pages", **self.ws(), label=str(foreign.id))
        assert not Page.objects.filter(name="Vaza").exists()

    def test_private_page_of_a_person_stays_hidden(self, mcp, docs):
        page = docs["pages"]["da_ana"]
        assert "não existe" in mcp.fails("retrieve_page", **self.ws(), project="WIKI", page_id=str(page.id))
        assert "não existe" in mcp.fails(
            "update_page", **self.ws(), project="WIKI", page_id=str(page.id), labels=["pap"]
        )

    def test_pagination_archived_subpages_and_deleted_tags(self, mcp, docs):
        first = mcp("list_pages", **self.ws(), limit=2)
        assert len(first["pages"]) == 2 and first["total"] == 3 and first["next_offset"] == 2
        assert len(mcp("list_pages", **self.ws(), limit=2, offset=2)["pages"]) == 1
        archived = docs["pages"]["checkout"]
        archived.archived_at = archived.created_at
        archived.save()
        assert self.listed(mcp) == ["Deploy", "Notas do Gil"]
        docs["labels"]["pap_wiki"].delete()
        assert "não existe" not in str(mcp("list_pages", **self.ws(), label="PaP"))
        assert self.listed(mcp, label="PaP") == []
