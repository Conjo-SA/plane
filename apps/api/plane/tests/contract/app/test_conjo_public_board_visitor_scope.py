# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""MAN-360: no board publicado, cada visitante só mexe no que é seu e só vê o que o board mostra.

Mesmo padrão do MAN-333: cada caso tem o controle positivo e o negativo.
"""

# Fixtures são compartilhadas com o teste do MAN-333 (o pytest injeta pelo nome).
# ruff: noqa: F401, F811

from unittest import mock
from uuid import uuid4

import pytest
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from plane.db.models import (
    FileAsset,
    IntakeIssue,
    Issue,
    IssueComment,
    IssueVote,
    State,
    User,
)

from .test_conjo_public_board_project_scope import detail, no_background_tasks, scenario, url

COMMENT = FileAsset.EntityTypeContext.COMMENT_DESCRIPTION
DESCRIPTION = FileAsset.EntityTypeContext.ISSUE_DESCRIPTION


@pytest.fixture(autouse=True)
def no_storage_task():
    with mock.patch("plane.space.views.asset.get_asset_object_metadata"):
        yield


def make_asset(scenario, created_by, entity_type=COMMENT, comment=None, deleted=False):
    asset = FileAsset.objects.create(
        attributes={"name": "print.png", "type": "image/png", "size": 10},
        asset=f"{scenario['project_a'].workspace_id}/{uuid4().hex}-print.png",
        size=10,
        workspace=scenario["project_a"].workspace,
        project=scenario["project_a"],
        entity_type=entity_type,
        comment=comment,
    )
    # O save() do modelo preenche created_by pelo usuário da requisição (vazio fora dela).
    FileAsset.all_objects.filter(pk=asset.pk).update(
        created_by=created_by, is_deleted=deleted, deleted_at=timezone.now() if deleted else None
    )
    return FileAsset.all_objects.get(pk=asset.pk)


def asset_url(scenario, asset):
    return f"/api/public/assets/v2/anchor/{scenario['anchor']}/{asset.id}/"


def restore_url(scenario, asset):
    return f"/api/public/assets/v2/anchor/{scenario['anchor']}/restore/{asset.id}/"


def internal_comment(scenario, actor):
    return IssueComment.objects.create(
        issue=scenario["issue_a"],
        project=scenario["project_a"],
        workspace=scenario["project_a"].workspace,
        comment_html="<p>nota interna</p>",
        access="INTERNAL",
        actor=actor,
    )


@pytest.mark.contract
class TestBoardAssetOwner:
    @pytest.mark.django_db
    def test_asset_of_other_person_cannot_be_changed(self, scenario):
        asset = make_asset(scenario, scenario["owner"])
        client = scenario["client"]

        assert client.delete(asset_url(scenario, asset)).status_code == status.HTTP_404_NOT_FOUND
        response = client.patch(asset_url(scenario, asset), {"attributes": {"name": "x"}}, format="json")
        assert response.status_code == status.HTTP_404_NOT_FOUND, detail(response)

        asset.refresh_from_db()
        assert asset.is_deleted is False
        assert asset.attributes["name"] == "print.png"

    @pytest.mark.django_db
    def test_deleted_asset_of_other_person_cannot_be_restored(self, scenario):
        asset = make_asset(scenario, scenario["owner"], deleted=True)
        response = scenario["client"].post(restore_url(scenario, asset))
        assert response.status_code == status.HTTP_404_NOT_FOUND, detail(response)
        assert FileAsset.all_objects.get(pk=asset.pk).is_deleted is True

    @pytest.mark.django_db
    def test_issue_description_image_cannot_be_changed_even_by_its_author(self, scenario):
        asset = make_asset(scenario, scenario["visitor"], entity_type=DESCRIPTION)
        client = scenario["client"]
        assert client.delete(asset_url(scenario, asset)).status_code == status.HTTP_404_NOT_FOUND
        assert client.patch(asset_url(scenario, asset), {}, format="json").status_code == status.HTTP_404_NOT_FOUND
        assert FileAsset.objects.get(pk=asset.pk).is_deleted is False

    @pytest.mark.django_db
    def test_own_asset_linked_to_internal_comment_cannot_be_changed(self, scenario):
        comment = internal_comment(scenario, scenario["visitor"])
        asset = make_asset(scenario, scenario["visitor"], comment=comment)
        assert scenario["client"].delete(asset_url(scenario, asset)).status_code == status.HTTP_404_NOT_FOUND
        assert FileAsset.objects.get(pk=asset.pk).is_deleted is False

    @pytest.mark.django_db
    def test_own_image_of_internal_comment_cannot_be_moved_to_public_comment(self, scenario):
        internal = internal_comment(scenario, scenario["visitor"])
        public = scenario["external_comment"](scenario["issue_a"], scenario["visitor"])
        asset = make_asset(scenario, scenario["visitor"], comment=internal)

        response = scenario["client"].post(
            f"/api/public/assets/v2/anchor/{scenario['anchor']}/{public.id}/bulk/",
            {"asset_ids": [str(asset.id)]},
            format="json",
        )

        assert response.status_code == status.HTTP_204_NO_CONTENT, detail(response)
        asset.refresh_from_db()
        assert asset.comment_id == internal.id

    @pytest.mark.django_db
    def test_upload_of_issue_description_image_is_refused(self, scenario):
        response = scenario["client"].post(
            f"/api/public/assets/v2/anchor/{scenario['anchor']}/",
            {"name": "print.png", "type": "image/png", "size": 10, "entity_type": DESCRIPTION},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST, detail(response)
        assert not FileAsset.objects.filter(entity_type=DESCRIPTION).exists()

    @pytest.mark.django_db
    def test_upload_flow_keeps_working_for_new_image(self, scenario):
        asset = make_asset(scenario, scenario["visitor"])
        response = scenario["client"].patch(
            asset_url(scenario, asset), {"attributes": {"name": "novo.png", "type": "image/png"}}, format="json"
        )
        assert response.status_code == status.HTTP_204_NO_CONTENT, detail(response)
        asset.refresh_from_db()
        assert asset.is_uploaded is True
        assert asset.attributes["name"] == "novo.png"

    @pytest.mark.django_db
    def test_own_image_of_own_comment_can_be_deleted_and_restored(self, scenario):
        comment = scenario["external_comment"](scenario["issue_a"], scenario["visitor"])
        asset = make_asset(scenario, scenario["visitor"], comment=comment)
        client = scenario["client"]

        assert client.delete(asset_url(scenario, asset)).status_code == status.HTTP_204_NO_CONTENT
        assert FileAsset.all_objects.get(pk=asset.pk).is_deleted is True
        assert client.post(restore_url(scenario, asset)).status_code == status.HTTP_204_NO_CONTENT
        assert FileAsset.all_objects.get(pk=asset.pk).is_deleted is False


@pytest.mark.contract
class TestBoardHiddenIssueComments:
    @pytest.fixture(params=["archived", "draft", "triage"])
    def hidden_issue(self, request, scenario):
        project = scenario["project_a"]
        if request.param == "archived":
            return Issue.objects.create(name="Arquivado", project=project, archived_at=timezone.now())
        if request.param == "draft":
            return Issue.objects.create(name="Rascunho", project=project, is_draft=True)
        triage = State.objects.create(
            name="Triagem", group="triage", project=project, workspace=project.workspace, sequence=65000
        )
        return Issue.objects.create(name="Em triagem", project=project, state=triage)

    @pytest.mark.django_db
    def test_comments_of_hidden_issue_are_not_listed(self, scenario, hidden_issue):
        scenario["external_comment"](hidden_issue, scenario["owner"])
        response = APIClient().get(url(scenario["anchor"], f"issues/{hidden_issue.id}/comments/"))
        assert response.status_code == status.HTTP_200_OK, detail(response)
        assert response.data == []

    @pytest.mark.django_db
    def test_comments_of_visible_issue_are_listed(self, scenario):
        response = APIClient().get(url(scenario["anchor"], f"issues/{scenario['issue_a'].id}/comments/"))
        assert response.status_code == status.HTTP_200_OK, detail(response)
        assert [str(c["id"]) for c in response.data] == [str(scenario["comment_a"].id)]


@pytest.mark.contract
class TestBoardIntakeRequester:
    def request_of(self, scenario, created_by, name):
        issue = Issue.objects.create(name=name, project=scenario["project_a"])
        intake_issue = IntakeIssue.objects.create(
            intake=scenario["intake_a"], project=scenario["project_a"], issue=issue
        )
        IntakeIssue.objects.filter(pk=intake_issue.pk).update(created_by=created_by)
        return intake_issue

    def list_url(self, scenario):
        return url(scenario["anchor"], f"intakes/{scenario['intake_a'].id}/intake-issues/")

    def detail_url(self, scenario, intake_issue):
        return f"{self.list_url(scenario)}{intake_issue.id}/"

    @pytest.mark.django_db
    def test_list_shows_only_own_requests(self, scenario):
        self.request_of(scenario, scenario["visitor"], "Meu pedido")
        self.request_of(scenario, scenario["owner"], "Pedido de terceiro")
        response = scenario["client"].get(self.list_url(scenario))
        assert response.status_code == status.HTTP_200_OK, detail(response)
        assert [i["name"] for i in response.data] == ["Meu pedido"]

    @pytest.mark.django_db
    def test_request_of_other_person_is_404(self, scenario):
        other = self.request_of(scenario, scenario["owner"], "Pedido de terceiro")
        response = scenario["client"].get(self.detail_url(scenario, other))
        assert response.status_code == status.HTTP_404_NOT_FOUND, detail(response)

    @pytest.mark.django_db
    def test_own_request_is_returned(self, scenario):
        own = self.request_of(scenario, scenario["visitor"], "Meu pedido")
        response = scenario["client"].get(self.detail_url(scenario, own))
        assert response.status_code == status.HTTP_200_OK, detail(response)
        assert response.data["name"] == "Meu pedido"

    @pytest.mark.django_db
    def test_deleted_request_leaves_the_list(self, scenario):
        own = self.request_of(scenario, scenario["visitor"], "Pedido excluído")
        own.delete()
        response = scenario["client"].get(self.list_url(scenario))
        assert response.status_code == status.HTTP_200_OK, detail(response)
        assert response.data == []

    @pytest.mark.django_db
    def test_request_sent_with_a_real_session_is_listed_for_its_author_only(self, scenario):
        """The list depends on created_by, filled from the logged-in user: session login, as in production."""
        author = APIClient()
        author.force_login(scenario["visitor"])
        response = author.post(self.list_url(scenario), {"issue": {"name": "Pedido real"}}, format="json")
        assert response.status_code == status.HTTP_200_OK, detail(response)
        request = IntakeIssue.objects.get(issue__name="Pedido real")
        assert request.created_by_id == scenario["visitor"].id

        assert [i["name"] for i in author.get(self.list_url(scenario)).data] == ["Pedido real"]

        other = APIClient()
        other.force_login(User.objects.create(email="outra@fora.com", username="outra"))
        assert other.get(self.list_url(scenario)).data == []

    @pytest.mark.django_db
    def test_anonymous_cannot_list(self, scenario):
        self.request_of(scenario, scenario["owner"], "Pedido de terceiro")
        response = APIClient().get(self.list_url(scenario))
        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN), detail(response)


@pytest.mark.contract
class TestBoardVoteValue:
    @pytest.mark.django_db
    @pytest.mark.parametrize("value", [99, 0, -2, "1", True, None])
    def test_invalid_vote_is_refused(self, scenario, value):
        response = scenario["client"].post(
            url(scenario["anchor"], f"issues/{scenario['issue_a'].id}/votes/"), {"vote": value}, format="json"
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST, detail(response)
        assert not IssueVote.objects.filter(issue=scenario["issue_a"]).exists()

    @pytest.mark.django_db
    @pytest.mark.parametrize("value", [1, -1])
    def test_valid_vote_is_saved(self, scenario, value):
        response = scenario["client"].post(
            url(scenario["anchor"], f"issues/{scenario['issue_a'].id}/votes/"), {"vote": value}, format="json"
        )
        assert response.status_code == status.HTTP_201_CREATED, detail(response)
        assert IssueVote.objects.get(issue=scenario["issue_a"], actor=scenario["visitor"]).vote == value


@pytest.mark.contract
class TestWorkspaceProjectBoardsRoute:
    @pytest.mark.django_db
    def test_broken_route_no_longer_exists(self, scenario):
        slug = scenario["project_a"].workspace.slug
        response = APIClient().get(f"/api/public/workspaces/{slug}/project-boards/")
        assert response.status_code == status.HTTP_404_NOT_FOUND, detail(response)
