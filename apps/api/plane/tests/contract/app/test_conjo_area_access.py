# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Permissions by area (MAN-467): who enters Clients, Docs, Time, Integrations and Archives."""

# Fixtures are shared with test_conjo_billing (pytest injects them by name).
# ruff: noqa: F401, F811

from unittest import mock

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from plane.db.models import (
    Client,
    Cycle,
    Issue,
    IssueClient,
    Module,
    Page,
    ProjectMember,
    ProjectPage,
    User,
    Workspace,
    WorkspaceAreaAccess,
    WorkspaceAreaMemberOverride,
    WorkspaceMember,
)
from plane.utils import conjo_areas

from .test_conjo_billing import client_, make_issue, project


@pytest.fixture(autouse=True)
def local_cache(settings):
    # The GitHub settings read the last webhook event from the cache; no Redis needed here.
    settings.CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}


@pytest.fixture(autouse=True)
def quiet():
    with (
        mock.patch("plane.bgtasks.conjo_billing_task.notify_low_balance.delay"),
        mock.patch("plane.bgtasks.page_transaction_task.page_transaction.delay"),
        mock.patch("plane.bgtasks.recent_visited_task.recent_visited_task.delay"),
        mock.patch("plane.bgtasks.issue_activities_task.issue_activity.delay"),
    ):
        yield


def api_for(user):
    api = APIClient()
    api.force_authenticate(user=user)
    api.user = user
    return api


def person(workspace, project, email, role):
    user = User.objects.create(email=email, username=email.split("@")[0], first_name=email.split("@")[0])
    WorkspaceMember.objects.create(workspace=workspace, member=user, role=role)
    ProjectMember.objects.create(project=project, member=user, role=role, is_active=True)
    return user


@pytest.fixture
def world(db, workspace, project, client_, create_user):
    """One work item for the client, a page, an archived item, cycle and module; a member and a guest."""
    project.guest_view_all_features = True
    project.save()
    issue = make_issue(project)
    IssueClient.objects.create(workspace=workspace, project=project, issue=issue, client=client_)
    page = Page.objects.create(name="Deploy", workspace=workspace, owned_by=create_user, access=Page.PUBLIC_ACCESS)
    ProjectPage.objects.create(page=page, project=project, workspace=workspace)
    archived = make_issue(project, name="Antigo")
    Issue.objects.filter(pk=archived.pk).update(archived_at=timezone.now())
    Cycle.objects.create(
        name="Sprint 1", project=project, workspace=workspace, owned_by=create_user, archived_at=timezone.now()
    )
    Module.objects.create(name="Módulo", project=project, workspace=workspace, archived_at=timezone.now())
    member = person(workspace, project, "membro@conjo.local", 15)
    guest = person(workspace, project, "convidado@conjo.local", 5)
    return {
        "issue": issue,
        "archived": archived,
        "page": page,
        "member": member,
        "guest": guest,
        "admin": create_user,
    }


def urls(workspace, project, client, world):
    ws = f"/api/workspaces/{workspace.slug}"
    pj = f"{ws}/projects/{project.id}"
    item = f"{pj}/issues/{world['issue'].id}"
    return {
        "clients": [
            f"{ws}/clients/",
            f"{ws}/clients/{client.id}/",
            f"{ws}/clients/options/",
            f"{ws}/clients/label-options/",
            f"{ws}/clients/{client.id}/ledger/",
            f"{ws}/clients/{client.id}/report/",
            f"{ws}/clients/{client.id}/report/deliveries/",
            f"{ws}/clients/{client.id}/timeline/",
            f"{item}/client/",
            f"{pj}/client-summary/",
        ],
        "docs": [
            f"{ws}/pages/",
            f"{pj}/pages/",
            f"{pj}/pages/{world['page'].id}/",
        ],
        "time": [
            f"{item}/time/",
            f"{item}/portal-budget/",
        ],
        "integrations": [
            f"{pj}/github-integration/",
            f"{pj}/chat-integration/",
        ],
        "archives": [
            f"{pj}/archived-issues/",
            f"{pj}/archived-cycles/",
            f"{pj}/archived-modules/",
        ],
    }


def get(api, url):
    return api.get(url).status_code


def configure(workspace, area, roles):
    WorkspaceAreaAccess.objects.update_or_create(workspace=workspace, area=area, defaults={"allowed_roles": roles})


ALL_AREAS = ["clients", "docs", "time", "integrations", "archives"]


@pytest.mark.contract
class TestDefaults:
    @pytest.mark.parametrize("area", ALL_AREAS)
    def test_admin_always_enters(self, workspace, project, client_, world, area):
        api = api_for(world["admin"])
        for url in urls(workspace, project, client_, world)[area]:
            assert get(api, url) == 200, url

    @pytest.mark.parametrize("area", ALL_AREAS)
    def test_admin_enters_even_with_every_role_off(self, workspace, project, client_, world, area):
        configure(workspace, area, [])
        api = api_for(world["admin"])
        for url in urls(workspace, project, client_, world)[area]:
            assert get(api, url) == 200, url

    def test_member_is_refused_in_clients_by_default(self, workspace, project, client_, world):
        api = api_for(world["member"])
        for url in urls(workspace, project, client_, world)["clients"]:
            response = api.get(url)
            assert response.status_code == 403, url
            assert "Clientes" in response.json()["error"]

    @pytest.mark.parametrize("area", ["docs", "time", "integrations", "archives"])
    def test_member_keeps_the_other_areas_by_default(self, workspace, project, client_, world, area):
        api = api_for(world["member"])
        for url in urls(workspace, project, client_, world)[area]:
            assert get(api, url) == 200, url

    def test_guest_keeps_what_it_had(self, workspace, project, client_, world):
        api = api_for(world["guest"])
        all_urls = urls(workspace, project, client_, world)
        for url in all_urls["docs"]:
            assert get(api, url) == 200, url
        # Guests read the time spent (without budget or client), as before.
        response = api.get(all_urls["time"][0])
        assert response.status_code == 200
        assert response.json()["client"] is None
        for area in ("clients", "integrations", "archives"):
            for url in all_urls[area]:
                assert get(api, url) == 403, url

    def test_outsider_enters_no_area(self, workspace, project, client_, world):
        outsider = User.objects.create(email="fora@x.com", username="fora")
        api = api_for(outsider)
        for area, area_urls in urls(workspace, project, client_, world).items():
            for url in area_urls:
                assert get(api, url) in (403, 404), url


@pytest.mark.contract
class TestConfiguration:
    @pytest.mark.parametrize("area", ["docs", "time", "integrations", "archives"])
    def test_turning_member_off_refuses_the_area(self, workspace, project, client_, world, area):
        configure(workspace, area, [5])
        api = api_for(world["member"])
        for url in urls(workspace, project, client_, world)[area]:
            assert get(api, url) == 403, url

    def test_turning_member_on_opens_clients_reads(self, workspace, project, client_, world):
        configure(workspace, "clients", [15])
        api = api_for(world["member"])
        for url in urls(workspace, project, client_, world)["clients"]:
            assert get(api, url) == 200, url

    def test_area_never_grants_a_write_the_role_does_not_allow(self, workspace, project, client_, world):
        configure(workspace, "clients", [15, 5])
        member = api_for(world["member"])
        assert (
            member.post(f"/api/workspaces/{workspace.slug}/clients/", {"name": "Novo"}, format="json").status_code
            == 403
        )
        assert (
            member.patch(
                f"/api/workspaces/{workspace.slug}/clients/{client_.id}/", {"name": "X"}, format="json"
            ).status_code
            == 403
        )
        # A guest with the area still reads no client list (the role does not allow it).
        guest = api_for(world["guest"])
        assert get(guest, f"/api/workspaces/{workspace.slug}/clients/") == 403
        assert not Client.objects.filter(name="Novo").exists()

    def test_guest_turned_off_in_docs_loses_the_pages(self, workspace, project, client_, world):
        configure(workspace, "docs", [15])
        api = api_for(world["guest"])
        for url in urls(workspace, project, client_, world)["docs"]:
            assert get(api, url) == 403, url
        assert get(api_for(world["member"]), f"/api/workspaces/{workspace.slug}/pages/") == 200

    def test_admin_saves_and_reads_the_configuration(self, session_client, workspace, world):
        url = f"/api/workspaces/{workspace.slug}/area-access/"
        response = session_client.get(url)
        assert response.status_code == 200
        by_key = {a["key"]: a for a in response.json()["areas"]}
        assert by_key["clients"]["allowed_roles"] == [] and by_key["clients"]["is_default"]
        assert by_key["docs"]["allowed_roles"] == [15, 5]
        response = session_client.put(url, {"areas": {"clients": [15], "docs": [15]}}, format="json")
        assert response.status_code == 200, response.content
        by_key = {a["key"]: a for a in response.json()["areas"]}
        assert by_key["clients"]["allowed_roles"] == [15] and not by_key["clients"]["is_default"]
        assert by_key["docs"]["allowed_roles"] == [15]
        # Saving again does not create a second row.
        session_client.put(url, {"areas": {"clients": [15, 5]}}, format="json")
        assert WorkspaceAreaAccess.objects.filter(workspace=workspace, area="clients").count() == 1

    @pytest.mark.parametrize(
        "payload",
        [
            {"areas": {"clients": [20]}},
            {"areas": {"financeiro": [15]}},
            {"areas": {"clients": "15"}},
            {"areas": {}},
            {},
        ],
    )
    def test_invalid_configuration_is_refused(self, session_client, workspace, payload):
        url = f"/api/workspaces/{workspace.slug}/area-access/"
        assert session_client.put(url, payload, format="json").status_code == 400
        assert not WorkspaceAreaAccess.objects.filter(workspace=workspace).exists()

    @pytest.mark.parametrize("who", ["member", "guest"])
    def test_member_and_guest_do_not_touch_the_configuration(self, workspace, world, who):
        api = api_for(world[who])
        base = f"/api/workspaces/{workspace.slug}/area-access/"
        assert api.get(base).status_code == 403
        assert api.put(base, {"areas": {"clients": [15, 5]}}, format="json").status_code == 403
        response = api.post(
            f"{base}overrides/", {"area": "clients", "member_id": str(world[who].id), "allow": True}, format="json"
        )
        assert response.status_code == 403
        assert not WorkspaceAreaAccess.objects.exists()
        assert not WorkspaceAreaMemberOverride.objects.exists()

    def test_member_cannot_remove_an_exception(self, session_client, workspace, world):
        base = f"/api/workspaces/{workspace.slug}/area-access/overrides/"
        response = session_client.post(
            base, {"area": "docs", "member_id": str(world["member"].id), "allow": False}, format="json"
        )
        override_id = response.json()["overrides"][0]["id"]
        assert api_for(world["member"]).delete(f"{base}{override_id}/").status_code == 403
        assert WorkspaceAreaMemberOverride.objects.filter(pk=override_id).exists()


@pytest.mark.contract
class TestExceptions:
    def base(self, workspace):
        return f"/api/workspaces/{workspace.slug}/area-access/overrides/"

    def test_exception_lets_one_member_into_clients(self, session_client, workspace, project, client_, world):
        other = person(workspace, project, "outro@conjo.local", 15)
        response = session_client.post(
            self.base(workspace),
            {"area": "clients", "member_id": str(world["member"].id), "allow": True},
            format="json",
        )
        assert response.status_code == 200, response.content
        assert response.json()["overrides"][0]["member"]["id"] == str(world["member"].id)
        for url in urls(workspace, project, client_, world)["clients"]:
            assert get(api_for(world["member"]), url) == 200, url
        # Only that person: the role keeps the rest out.
        assert get(api_for(other), f"/api/workspaces/{workspace.slug}/clients/") == 403

    def test_exception_blocks_one_member(self, session_client, workspace, project, client_, world):
        session_client.post(
            self.base(workspace), {"area": "docs", "member_id": str(world["member"].id), "allow": False}, format="json"
        )
        for url in urls(workspace, project, client_, world)["docs"]:
            assert get(api_for(world["member"]), url) == 403, url
        assert get(api_for(world["guest"]), f"/api/workspaces/{workspace.slug}/pages/") == 200

    def test_exception_wins_over_the_role(self, session_client, workspace, project, client_, world):
        configure(workspace, "archives", [])
        session_client.post(
            self.base(workspace),
            {"area": "archives", "member_id": str(world["member"].id), "allow": True},
            format="json",
        )
        for url in urls(workspace, project, client_, world)["archives"]:
            assert get(api_for(world["member"]), url) == 200, url

    def test_exception_never_blocks_an_admin(self, session_client, workspace, project, client_, world):
        other_admin = person(workspace, project, "admin2@conjo.local", 20)
        response = session_client.post(
            self.base(workspace), {"area": "clients", "member_id": str(other_admin.id), "allow": False}, format="json"
        )
        assert response.status_code == 400
        assert not WorkspaceAreaMemberOverride.objects.exists()
        # Even a block saved before the person became admin is ignored.
        WorkspaceAreaMemberOverride.objects.create(workspace=workspace, area="clients", member=other_admin, allow=False)
        for url in urls(workspace, project, client_, world)["clients"]:
            assert get(api_for(other_admin), url) == 200, url
        assert conjo_areas.areas_for(other_admin, workspace.slug)["clients"] is True

    def test_exception_for_someone_outside_the_workspace_is_refused(self, session_client, workspace):
        outsider = User.objects.create(email="fora@x.com", username="fora")
        response = session_client.post(
            self.base(workspace), {"area": "clients", "member_id": str(outsider.id), "allow": True}, format="json"
        )
        assert response.status_code == 404
        assert not WorkspaceAreaMemberOverride.objects.exists()

    @pytest.mark.parametrize(
        "payload",
        [{"area": "financeiro", "allow": True}, {"area": "clients", "allow": "sim"}, {"area": "clients"}],
    )
    def test_invalid_exception_is_refused(self, session_client, workspace, world, payload):
        payload = {**payload, "member_id": str(world["member"].id)}
        assert session_client.post(self.base(workspace), payload, format="json").status_code == 400

    def test_changing_and_removing_an_exception(self, session_client, workspace, project, client_, world):
        member_id = str(world["member"].id)
        session_client.post(
            self.base(workspace), {"area": "clients", "member_id": member_id, "allow": True}, format="json"
        )
        response = session_client.post(
            self.base(workspace), {"area": "clients", "member_id": member_id, "allow": False}, format="json"
        )
        overrides = response.json()["overrides"]
        assert len(overrides) == 1 and overrides[0]["allow"] is False
        response = session_client.delete(f"{self.base(workspace)}{overrides[0]['id']}/")
        assert response.status_code == 200
        assert response.json()["overrides"] == []
        # Soft delete: the row stays, out of the default manager, and the role decides again.
        assert WorkspaceAreaMemberOverride.all_objects.filter(member_id=member_id).count() == 1
        assert get(api_for(world["member"]), f"/api/workspaces/{workspace.slug}/clients/") == 403
        # It can be created again after removal (unique only among live rows).
        response = session_client.post(
            self.base(workspace), {"area": "clients", "member_id": member_id, "allow": True}, format="json"
        )
        assert response.status_code == 200
        assert get(api_for(world["member"]), f"/api/workspaces/{workspace.slug}/clients/") == 200


@pytest.mark.contract
class TestWorkspaceIsolation:
    @pytest.fixture
    def other(self, db):
        owner = User.objects.create(email="dono@outra.com", username="dono")
        ws = Workspace.objects.create(name="Outra", owner=owner, slug="outra")
        WorkspaceMember.objects.create(workspace=ws, member=owner, role=20)
        return {"workspace": ws, "owner": owner}

    def test_admin_of_another_workspace_does_not_see_the_configuration(self, workspace, world, other):
        api = api_for(other["owner"])
        base = f"/api/workspaces/{workspace.slug}/area-access/"
        assert api.get(base).status_code == 403
        assert api.put(base, {"areas": {"clients": [15, 5]}}, format="json").status_code == 403
        assert not WorkspaceAreaAccess.objects.exists()

    def test_configuration_of_one_workspace_does_not_apply_to_another(self, workspace, world, other):
        member = User.objects.create(email="m@outra.com", username="m-outra")
        WorkspaceMember.objects.create(workspace=other["workspace"], member=member, role=15)
        configure(workspace, "clients", [15])
        assert conjo_areas.has_area_access(world["member"], workspace.slug, "clients")
        assert not conjo_areas.has_area_access(member, other["workspace"].slug, "clients")
        assert get(api_for(member), "/api/workspaces/outra/clients/") == 403

    def test_exception_of_one_workspace_does_not_apply_to_another(self, session_client, workspace, world, other):
        WorkspaceMember.objects.create(workspace=other["workspace"], member=world["member"], role=15)
        response = session_client.post(
            f"/api/workspaces/{workspace.slug}/area-access/overrides/",
            {"area": "clients", "member_id": str(world["member"].id), "allow": True},
            format="json",
        )
        assert response.status_code == 200
        assert conjo_areas.has_area_access(world["member"], workspace.slug, "clients")
        assert not conjo_areas.has_area_access(world["member"], "outra", "clients")

    def test_exception_cannot_be_removed_through_another_workspace(self, session_client, workspace, world, other):
        response = session_client.post(
            f"/api/workspaces/{workspace.slug}/area-access/overrides/",
            {"area": "docs", "member_id": str(world["member"].id), "allow": False},
            format="json",
        )
        override_id = response.json()["overrides"][0]["id"]
        api = api_for(other["owner"])
        assert api.delete(f"/api/workspaces/outra/area-access/overrides/{override_id}/").status_code == 404
        assert WorkspaceAreaMemberOverride.objects.filter(pk=override_id).exists()

    def test_exception_cannot_target_a_member_of_another_workspace(self, session_client, workspace, other):
        response = session_client.post(
            f"/api/workspaces/{workspace.slug}/area-access/overrides/",
            {"area": "clients", "member_id": str(other["owner"].id), "allow": True},
            format="json",
        )
        assert response.status_code == 404


@pytest.mark.contract
class TestMyAreas:
    def url(self, workspace):
        return f"/api/workspaces/{workspace.slug}/area-access/me/"

    def test_member_defaults(self, workspace, world):
        response = api_for(world["member"]).get(self.url(workspace))
        assert response.status_code == 200
        assert response.json()["areas"] == {
            "clients": False,
            "docs": True,
            "time": True,
            "integrations": True,
            "archives": True,
        }

    def test_guest_defaults(self, workspace, world):
        areas = api_for(world["guest"]).get(self.url(workspace)).json()["areas"]
        assert areas == {"clients": False, "docs": True, "time": True, "integrations": False, "archives": False}

    def test_admin_enters_everything(self, session_client, workspace, world):
        for area in ALL_AREAS:
            configure(workspace, area, [])
        areas = session_client.get(self.url(workspace)).json()["areas"]
        assert all(areas.values())

    def test_follows_configuration_and_exceptions(self, workspace, world):
        configure(workspace, "clients", [15])
        WorkspaceAreaMemberOverride.objects.create(
            workspace=workspace, area="docs", member=world["member"], allow=False
        )
        areas = api_for(world["member"]).get(self.url(workspace)).json()["areas"]
        assert areas["clients"] is True and areas["docs"] is False

    def test_outsider_is_refused(self, workspace, world):
        outsider = User.objects.create(email="fora@x.com", username="fora")
        assert api_for(outsider).get(self.url(workspace)).status_code == 403


@pytest.mark.contract
class TestSideEffects:
    def test_time_widget_hides_the_client_without_the_clients_area(self, workspace, project, client_, world):
        url = f"/api/workspaces/{workspace.slug}/projects/{project.id}/issues/{world['issue'].id}/time/"
        assert api_for(world["member"]).get(url).json()["client"] is None
        configure(workspace, "clients", [15])
        assert api_for(world["member"]).get(url).json()["client"]["name"] == client_.name

    def test_search_hides_pages_without_the_docs_area(self, workspace, project, world):
        WorkspaceAreaMemberOverride.objects.create(
            workspace=workspace, area="docs", member=world["member"], allow=False
        )
        url = f"/api/workspaces/{workspace.slug}/search/?search=Deploy&entities=page"
        response = api_for(world["member"]).get(url)
        assert response.status_code == 200
        assert response.json()["results"]["page"] == []
        assert len(api_for(world["admin"]).get(url).json()["results"]["page"]) == 1


@pytest.mark.contract
class TestExternalApi:
    """The v1 API (personal API keys) goes through the same gate on the archive endpoints."""

    def api_key_for(self, user):
        from plane.db.models.api import APIToken

        token = APIToken.objects.create(user=user, label="teste", token=f"tok-{user.id.hex}")
        api = APIClient()
        api.credentials(HTTP_X_API_KEY=token.token)
        return api

    def test_archived_cycles_follow_the_area(self, workspace, project, world):
        url = f"/api/v1/workspaces/{workspace.slug}/projects/{project.id}/archived-cycles/"
        api = self.api_key_for(world["member"])
        assert api.get(url).status_code == 200
        WorkspaceAreaMemberOverride.objects.create(
            workspace=workspace, area="archives", member=world["member"], allow=False
        )
        assert api.get(url).status_code == 403
        assert self.api_key_for(world["admin"]).get(url).status_code == 200


@pytest.mark.contract
class TestArchiveSidePaths:
    """Archived data reached through the generic endpoints also needs the Archives area (security review)."""

    @pytest.fixture
    def blocked(self, workspace, world):
        WorkspaceAreaMemberOverride.objects.create(
            workspace=workspace, area="archives", member=world["member"], allow=False
        )
        return api_for(world["member"])

    def test_archiving_by_patch_is_refused(self, workspace, project, world, blocked):
        url = f"/api/workspaces/{workspace.slug}/projects/{project.id}/issues/{world['issue'].id}/"
        assert blocked.patch(url, {"archived_at": "2026-11-10"}, format="json").status_code == 403
        world["issue"].refresh_from_db()
        assert world["issue"].archived_at is None
        # Other updates keep working.
        assert blocked.patch(url, {"name": "Novo nome"}, format="json").status_code == 204

    def test_archived_item_detail_is_refused(self, workspace, project, world, blocked):
        archived = world["archived"]
        url = f"/api/workspaces/{workspace.slug}/projects/{project.id}/issues/{archived.id}/"
        assert blocked.get(url).status_code == 403
        by_key = f"/api/workspaces/{workspace.slug}/work-items/{project.identifier}-{archived.sequence_id}/"
        assert blocked.get(by_key).status_code == 403
        assert api_for(world["admin"]).get(url).status_code == 200
        # A live item still opens.
        live = f"/api/workspaces/{workspace.slug}/projects/{project.id}/issues/{world['issue'].id}/"
        assert blocked.get(live).status_code == 200

    def test_archived_projects_leave_the_project_list(self, workspace, project, world, blocked, create_user):
        from plane.db.models import Project

        old = Project.objects.create(
            name="Antigo", identifier="OLD", workspace=workspace, created_by=create_user, archived_at=timezone.now()
        )
        ProjectMember.objects.create(project=old, member=world["member"], role=15, is_active=True)
        for suffix in ("", "details/"):
            url = f"/api/workspaces/{workspace.slug}/projects/{suffix}"
            response = blocked.get(url)
            assert response.status_code == 200, url
            assert str(old.id) not in {p["id"] for p in response.json()}, url
            assert str(old.id) in {p["id"] for p in api_for(world["admin"]).get(url).json()}, url

    def test_slug_that_looks_like_another_workspace_id_is_still_a_slug(self, workspace, world):
        trap = Workspace.objects.create(name="Armadilha", owner=world["guest"], slug=str(workspace.id))
        WorkspaceMember.objects.create(workspace=trap, member=world["admin"], role=5)
        # Admin in ``workspace``, guest in the workspace whose slug is that id.
        assert not conjo_areas.has_area_access(world["admin"], str(workspace.id), "clients")
        assert conjo_areas.has_area_access(world["admin"], workspace.slug, "clients")
