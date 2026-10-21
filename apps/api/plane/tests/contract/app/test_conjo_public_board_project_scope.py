# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""MAN-333: o board publicado só mexe em chamado, comentário e Entrada do próprio projeto.

Os endpoints públicos (``/api/public/anchor/<anchor>/...``) recebem ``issue_id``,
``comment_id`` e ``intake_id`` pela URL ou pelo corpo. Antes, gravavam com o
``project_id`` do board e o id recebido sem conferir que ele pertence a esse
projeto: quem conhecia o UUID de um chamado comentava, reagia ou votava nele a
partir de qualquer board publicado. Cada caso aqui tem o controle positivo
(mesmo projeto funciona) e o negativo (outro projeto responde 404 e não grava).
"""

from unittest import mock
from uuid import uuid4

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from plane.db.models import (
    CommentReaction,
    DeployBoard,
    FileAsset,
    Intake,
    IntakeIssue,
    Issue,
    IssueComment,
    IssueReaction,
    IssueVote,
    Project,
    State,
    User,
)

THUMBS_UP = "128077"


def make_project(workspace, owner, name, identifier):
    project = Project.objects.create(name=name, identifier=identifier, workspace=workspace, created_by=owner)
    State.objects.create(name="Backlog", group="backlog", project=project, workspace=workspace, default=True)
    return project


@pytest.fixture
def scenario(db, workspace, create_user):
    """Projeto A publicado (comentários, reações, votos e Entrada) e projeto B, privado, no mesmo workspace."""
    project_a = make_project(workspace, create_user, "Publicado", "PUB")
    project_b = make_project(workspace, create_user, "Privado", "PRV")
    intake_a = Intake.objects.create(name="Entrada A", project=project_a, workspace=workspace)
    intake_b = Intake.objects.create(name="Entrada B", project=project_b, workspace=workspace)
    board = DeployBoard.objects.create(
        workspace=workspace,
        project=project_a,
        entity_name="project",
        entity_identifier=project_a.id,
        is_comments_enabled=True,
        is_reactions_enabled=True,
        is_votes_enabled=True,
        intake=intake_a,
    )
    issue_a = Issue.objects.create(name="Chamado público", project=project_a)
    issue_b = Issue.objects.create(name="Chamado de outro projeto", project=project_b)

    visitor = User.objects.create(email=f"visitante-{uuid4().hex[:8]}@fora.com", username=f"vis_{uuid4().hex[:8]}")
    client = APIClient()
    client.force_authenticate(user=visitor)

    def external_comment(issue, actor):
        return IssueComment.objects.create(
            issue=issue,
            project=issue.project,
            workspace=workspace,
            comment_html="<p>resposta</p>",
            access="EXTERNAL",
            actor=actor,
        )

    return {
        "anchor": board.anchor,
        "board": board,
        "client": client,
        "visitor": visitor,
        "owner": create_user,
        "project_a": project_a,
        "project_b": project_b,
        "intake_a": intake_a,
        "intake_b": intake_b,
        "issue_a": issue_a,
        "issue_b": issue_b,
        "comment_a": external_comment(issue_a, create_user),
        "comment_b": external_comment(issue_b, create_user),
        "external_comment": external_comment,
    }


@pytest.fixture(autouse=True)
def no_background_tasks():
    with (
        mock.patch("plane.space.views.issue.issue_activity"),
        mock.patch("plane.space.views.intake.issue_activity"),
        mock.patch("plane.db.mixins.soft_delete_related_objects"),
    ):
        yield


def url(anchor, path):
    return f"/api/public/anchor/{anchor}/{path}"


def detail(response):
    return f"Got {response.status_code}: {getattr(response, 'data', None)!r}"


@pytest.mark.contract
class TestPublicBoardComments:
    @pytest.mark.django_db
    def test_comment_on_issue_of_other_project_is_404(self, scenario):
        before = IssueComment.objects.filter(issue=scenario["issue_b"]).count()
        response = scenario["client"].post(
            url(scenario["anchor"], f"issues/{scenario['issue_b'].id}/comments/"),
            {"comment_html": "<p>invasão</p>"},
            format="json",
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND, detail(response)
        assert IssueComment.objects.filter(issue=scenario["issue_b"]).count() == before
        assert not IssueComment.objects.filter(comment_html="<p>invasão</p>").exists()

    @pytest.mark.django_db
    def test_comment_on_issue_of_board_project_is_created(self, scenario):
        response = scenario["client"].post(
            url(scenario["anchor"], f"issues/{scenario['issue_a'].id}/comments/"),
            {"comment_html": "<p>olá</p>"},
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED, detail(response)
        comment = IssueComment.objects.get(pk=response.data["id"])
        assert comment.issue_id == scenario["issue_a"].id
        assert comment.project_id == scenario["project_a"].id
        assert comment.access == "EXTERNAL"

    @pytest.mark.django_db
    def test_comment_on_unknown_issue_is_404(self, scenario):
        response = scenario["client"].post(
            url(scenario["anchor"], f"issues/{uuid4()}/comments/"),
            {"comment_html": "<p>fantasma</p>"},
            format="json",
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND, detail(response)

    @pytest.mark.django_db
    def test_list_does_not_expose_comments_of_other_project(self, scenario):
        response = scenario["client"].get(url(scenario["anchor"], f"issues/{scenario['issue_b'].id}/comments/"))
        assert response.status_code == status.HTTP_200_OK, detail(response)
        assert response.data == []

    @pytest.mark.django_db
    def test_list_returns_comments_of_board_issue(self, scenario):
        response = scenario["client"].get(url(scenario["anchor"], f"issues/{scenario['issue_a'].id}/comments/"))
        assert response.status_code == status.HTTP_200_OK, detail(response)
        assert [str(c["id"]) for c in response.data] == [str(scenario["comment_a"].id)]

    @pytest.mark.django_db
    def test_edit_and_delete_own_comment_of_other_project_is_404(self, scenario):
        own_in_b = scenario["external_comment"](scenario["issue_b"], scenario["visitor"])
        path = url(scenario["anchor"], f"issues/{scenario['issue_b'].id}/comments/{own_in_b.id}/")

        response = scenario["client"].patch(path, {"comment_html": "<p>editado</p>"}, format="json")
        assert response.status_code == status.HTTP_404_NOT_FOUND, detail(response)
        response = scenario["client"].delete(path)
        assert response.status_code == status.HTTP_404_NOT_FOUND, detail(response)

        own_in_b.refresh_from_db()
        assert own_in_b.comment_html == "<p>resposta</p>"
        assert own_in_b.deleted_at is None

    @pytest.mark.django_db
    def test_comment_of_board_issue_cannot_be_reached_through_other_issue_id(self, scenario):
        """O comentário tem de ser do chamado da URL, não só do projeto."""
        own_in_a = scenario["external_comment"](scenario["issue_a"], scenario["visitor"])
        other_issue_a = Issue.objects.create(name="Outro chamado público", project=scenario["project_a"])
        path = url(scenario["anchor"], f"issues/{other_issue_a.id}/comments/{own_in_a.id}/")
        response = scenario["client"].patch(path, {"comment_html": "<p>editado</p>"}, format="json")
        assert response.status_code == status.HTTP_404_NOT_FOUND, detail(response)

    @pytest.mark.django_db
    def test_edit_and_delete_own_comment_of_board_project_work(self, scenario):
        own_in_a = scenario["external_comment"](scenario["issue_a"], scenario["visitor"])
        path = url(scenario["anchor"], f"issues/{scenario['issue_a'].id}/comments/{own_in_a.id}/")

        response = scenario["client"].patch(path, {"comment_html": "<p>editado</p>"}, format="json")
        assert response.status_code == status.HTTP_200_OK, detail(response)
        response = scenario["client"].delete(path)
        assert response.status_code == status.HTTP_204_NO_CONTENT, detail(response)


@pytest.mark.contract
class TestPublicBoardIssueReactions:
    @pytest.mark.django_db
    def test_react_on_issue_of_other_project_is_404(self, scenario):
        response = scenario["client"].post(
            url(scenario["anchor"], f"issues/{scenario['issue_b'].id}/reactions/"),
            {"reaction": THUMBS_UP},
            format="json",
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND, detail(response)
        assert not IssueReaction.objects.filter(issue=scenario["issue_b"]).exists()

    @pytest.mark.django_db
    def test_react_on_board_issue_is_created_and_listed(self, scenario):
        response = scenario["client"].post(
            url(scenario["anchor"], f"issues/{scenario['issue_a'].id}/reactions/"),
            {"reaction": THUMBS_UP},
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED, detail(response)
        assert IssueReaction.objects.filter(issue=scenario["issue_a"], actor=scenario["visitor"]).exists()

        response = scenario["client"].get(url(scenario["anchor"], f"issues/{scenario['issue_a'].id}/reactions/"))
        assert response.status_code == status.HTTP_200_OK, detail(response)
        assert [r["reaction"] for r in response.data] == [THUMBS_UP]

    @pytest.mark.django_db
    def test_list_does_not_expose_reactions_of_other_project(self, scenario):
        IssueReaction.objects.create(
            issue=scenario["issue_b"], project=scenario["project_b"], actor=scenario["owner"], reaction=THUMBS_UP
        )
        response = scenario["client"].get(url(scenario["anchor"], f"issues/{scenario['issue_b'].id}/reactions/"))
        assert response.status_code == status.HTTP_200_OK, detail(response)
        assert response.data == []

    @pytest.mark.django_db
    def test_remove_own_reaction_of_other_project_is_404(self, scenario):
        reaction = IssueReaction.objects.create(
            issue=scenario["issue_b"], project=scenario["project_b"], actor=scenario["visitor"], reaction=THUMBS_UP
        )
        response = scenario["client"].delete(
            url(scenario["anchor"], f"issues/{scenario['issue_b'].id}/reactions/{THUMBS_UP}/")
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND, detail(response)
        reaction.refresh_from_db()
        assert reaction.deleted_at is None


@pytest.mark.contract
class TestPublicBoardCommentReactions:
    @pytest.mark.django_db
    def test_react_on_comment_of_other_project_is_404(self, scenario):
        response = scenario["client"].post(
            url(scenario["anchor"], f"comments/{scenario['comment_b'].id}/reactions/"),
            {"reaction": THUMBS_UP},
            format="json",
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND, detail(response)
        assert not CommentReaction.objects.filter(comment=scenario["comment_b"]).exists()

    @pytest.mark.django_db
    def test_react_on_internal_comment_of_board_project_is_404(self, scenario):
        """Nota interna não aparece no board; também não recebe reação por ele."""
        internal = IssueComment.objects.create(
            issue=scenario["issue_a"],
            project=scenario["project_a"],
            workspace=scenario["project_a"].workspace,
            comment_html="<p>nota interna</p>",
            access="INTERNAL",
            actor=scenario["owner"],
        )
        response = scenario["client"].post(
            url(scenario["anchor"], f"comments/{internal.id}/reactions/"),
            {"reaction": THUMBS_UP},
            format="json",
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND, detail(response)
        assert not CommentReaction.objects.filter(comment=internal).exists()

    @pytest.mark.django_db
    def test_react_on_comment_of_board_project_is_created(self, scenario):
        response = scenario["client"].post(
            url(scenario["anchor"], f"comments/{scenario['comment_a'].id}/reactions/"),
            {"reaction": THUMBS_UP},
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED, detail(response)
        reaction = CommentReaction.objects.get(comment=scenario["comment_a"], actor=scenario["visitor"])
        assert reaction.project_id == scenario["project_a"].id


@pytest.mark.contract
class TestPublicBoardVotes:
    @pytest.mark.django_db
    def test_vote_on_issue_of_other_project_is_404(self, scenario):
        response = scenario["client"].post(
            url(scenario["anchor"], f"issues/{scenario['issue_b'].id}/votes/"), {"vote": 1}, format="json"
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND, detail(response)
        assert not IssueVote.objects.filter(issue=scenario["issue_b"]).exists()

    @pytest.mark.django_db
    def test_vote_on_board_issue_is_created_and_listed(self, scenario):
        response = scenario["client"].post(
            url(scenario["anchor"], f"issues/{scenario['issue_a'].id}/votes/"), {"vote": 1}, format="json"
        )
        assert response.status_code == status.HTTP_201_CREATED, detail(response)
        assert IssueVote.objects.filter(issue=scenario["issue_a"], actor=scenario["visitor"], vote=1).exists()

        response = scenario["client"].get(url(scenario["anchor"], f"issues/{scenario['issue_a'].id}/votes/"))
        assert response.status_code == status.HTTP_200_OK, detail(response)
        assert len(response.data) == 1

    @pytest.mark.django_db
    def test_vote_is_refused_when_votes_are_disabled(self, scenario):
        DeployBoard.objects.filter(pk=scenario["board"].pk).update(is_votes_enabled=False)
        response = scenario["client"].post(
            url(scenario["anchor"], f"issues/{scenario['issue_a'].id}/votes/"), {"vote": 1}, format="json"
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST, detail(response)
        assert not IssueVote.objects.filter(issue=scenario["issue_a"]).exists()


@pytest.mark.contract
class TestPublicBoardIntake:
    @pytest.mark.django_db
    def test_intake_of_other_project_is_404(self, scenario):
        response = scenario["client"].post(
            url(scenario["anchor"], f"intakes/{scenario['intake_b'].id}/intake-issues/"),
            {"issue": {"name": "Pedido"}},
            format="json",
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND, detail(response)
        assert not IntakeIssue.objects.filter(intake=scenario["intake_b"]).exists()
        assert not Issue.objects.filter(name="Pedido").exists()

    @pytest.mark.django_db
    def test_intake_of_board_project_creates_request(self, scenario):
        response = scenario["client"].post(
            url(scenario["anchor"], f"intakes/{scenario['intake_a'].id}/intake-issues/"),
            {"issue": {"name": "Pedido"}},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK, detail(response)
        assert IntakeIssue.objects.filter(intake=scenario["intake_a"], issue__name="Pedido").exists()


@pytest.mark.contract
class TestPublicBoardCommentAssets:
    def asset(self, scenario):
        return FileAsset.objects.create(
            attributes={"name": "print.png", "type": "image/png", "size": 10},
            asset=f"{scenario['project_a'].workspace_id}/{uuid4().hex}-print.png",
            size=10,
            workspace=scenario["project_a"].workspace,
            project=scenario["project_a"],
            entity_type=FileAsset.EntityTypeContext.COMMENT_DESCRIPTION,
            created_by=scenario["visitor"],
        )

    @pytest.mark.django_db
    def test_bulk_link_to_comment_of_other_project_is_404(self, scenario):
        asset = self.asset(scenario)
        response = scenario["client"].post(
            f"/api/public/assets/v2/anchor/{scenario['anchor']}/{scenario['comment_b'].id}/bulk/",
            {"asset_ids": [str(asset.id)]},
            format="json",
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND, detail(response)
        asset.refresh_from_db()
        assert asset.comment_id is None

    @pytest.mark.django_db
    def test_bulk_link_to_comment_of_board_project_works(self, scenario):
        asset = self.asset(scenario)
        response = scenario["client"].post(
            f"/api/public/assets/v2/anchor/{scenario['anchor']}/{scenario['comment_a'].id}/bulk/",
            {"asset_ids": [str(asset.id)]},
            format="json",
        )
        assert response.status_code == status.HTTP_204_NO_CONTENT, detail(response)
        asset.refresh_from_db()
        assert asset.comment_id == scenario["comment_a"].id

    @pytest.mark.django_db
    def test_upload_for_comment_of_other_project_is_404(self, scenario):
        with mock.patch("plane.space.views.asset.S3Storage") as storage:
            storage.return_value.generate_presigned_post.return_value = {"url": "https://s3.test", "fields": {}}
            response = scenario["client"].post(
                f"/api/public/assets/v2/anchor/{scenario['anchor']}/",
                {
                    "name": "print.png",
                    "type": "image/png",
                    "size": 10,
                    "entity_type": FileAsset.EntityTypeContext.COMMENT_DESCRIPTION,
                    "entity_identifier": str(scenario["comment_b"].id),
                },
                format="json",
            )
        assert response.status_code == status.HTTP_404_NOT_FOUND, detail(response)
        assert not FileAsset.objects.filter(comment=scenario["comment_b"]).exists()

    @pytest.mark.django_db
    def test_upload_for_comment_of_board_project_works(self, scenario):
        with mock.patch("plane.space.views.asset.S3Storage") as storage:
            storage.return_value.generate_presigned_post.return_value = {"url": "https://s3.test", "fields": {}}
            response = scenario["client"].post(
                f"/api/public/assets/v2/anchor/{scenario['anchor']}/",
                {
                    "name": "print.png",
                    "type": "image/png",
                    "size": 10,
                    "entity_type": FileAsset.EntityTypeContext.COMMENT_DESCRIPTION,
                    "entity_identifier": str(scenario["comment_a"].id),
                },
                format="json",
            )
        assert response.status_code == status.HTTP_200_OK, detail(response)
        assert FileAsset.objects.filter(comment=scenario["comment_a"]).exists()
