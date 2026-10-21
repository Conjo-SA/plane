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

import json
from unittest import mock
from uuid import uuid4

import pytest
from django.utils import timezone
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
    Workspace,
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
class TestPublicBoardCommentFields:
    """O visitante só escreve o texto do comentário; autor, visibilidade e pai são do servidor."""

    @pytest.mark.django_db
    def test_edit_cannot_change_actor_or_access(self, scenario):
        own = scenario["external_comment"](scenario["issue_a"], scenario["visitor"])
        response = scenario["client"].patch(
            url(scenario["anchor"], f"issues/{scenario['issue_a'].id}/comments/{own.id}/"),
            {
                "comment_html": "<p>editado</p>",
                "actor": str(scenario["owner"].id),
                "access": "INTERNAL",
                "parent": str(scenario["comment_b"].id),
                "external_source": "INTAKE_PORTAL",
                "external_id": "x",
            },
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK, detail(response)
        own.refresh_from_db()
        assert own.comment_html == "<p>editado</p>"
        assert own.actor_id == scenario["visitor"].id
        assert own.access == "EXTERNAL"
        assert own.parent_id is None
        assert own.external_source is None
        assert own.external_id is None

    @pytest.mark.django_db
    def test_create_ignores_actor_access_and_parent(self, scenario):
        response = scenario["client"].post(
            url(scenario["anchor"], f"issues/{scenario['issue_a'].id}/comments/"),
            {
                "comment_html": "<p>novo</p>",
                "actor": str(scenario["owner"].id),
                "access": "INTERNAL",
                "parent": str(scenario["comment_b"].id),
                "external_source": "INTAKE_PORTAL",
            },
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED, detail(response)
        comment = IssueComment.objects.get(pk=response.data["id"])
        assert comment.actor_id == scenario["visitor"].id
        assert comment.access == "EXTERNAL"
        assert comment.parent_id is None
        assert comment.external_source is None

    @pytest.mark.django_db
    def test_edit_sends_sanitized_html_to_activity(self, scenario):
        """A atividade (e o e-mail aos membros) recebe o HTML já sanitizado, nunca o corpo cru."""
        own = scenario["external_comment"](scenario["issue_a"], scenario["visitor"])
        raw = '<p>oi</p><script>alert(1)</script><img src=x onerror="alert(2)">'
        with mock.patch("plane.space.views.issue.issue_activity") as activity:
            response = scenario["client"].patch(
                url(scenario["anchor"], f"issues/{scenario['issue_a'].id}/comments/{own.id}/"),
                {"comment_html": raw},
                format="json",
            )
        assert response.status_code == status.HTTP_200_OK, detail(response)
        own.refresh_from_db()
        assert "script" not in own.comment_html and "onerror" not in own.comment_html

        requested = json.loads(activity.delay.call_args.kwargs["requested_data"])
        assert requested["comment_html"] == own.comment_html
        assert "script" not in requested["comment_html"]
        assert "onerror" not in requested["comment_html"]


@pytest.mark.contract
class TestPublicBoardHiddenIssues:
    """Chamado que o board não mostra (arquivado, rascunho, triagem) também não recebe interação."""

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
    def test_comment_react_and_vote_on_hidden_issue_are_404(self, scenario, hidden_issue):
        client = scenario["client"]
        anchor = scenario["anchor"]
        response = client.post(
            url(anchor, f"issues/{hidden_issue.id}/comments/"), {"comment_html": "<p>x</p>"}, format="json"
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND, detail(response)
        response = client.post(
            url(anchor, f"issues/{hidden_issue.id}/reactions/"), {"reaction": THUMBS_UP}, format="json"
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND, detail(response)
        response = client.post(url(anchor, f"issues/{hidden_issue.id}/votes/"), {"vote": 1}, format="json")
        assert response.status_code == status.HTTP_404_NOT_FOUND, detail(response)

        assert not IssueComment.objects.filter(issue=hidden_issue).exists()
        assert not IssueReaction.objects.filter(issue=hidden_issue).exists()
        assert not IssueVote.objects.filter(issue=hidden_issue).exists()

    @pytest.mark.django_db
    def test_react_on_comment_of_hidden_issue_is_404(self, scenario, hidden_issue):
        comment = scenario["external_comment"](hidden_issue, scenario["owner"])
        response = scenario["client"].post(
            url(scenario["anchor"], f"comments/{comment.id}/reactions/"), {"reaction": THUMBS_UP}, format="json"
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND, detail(response)
        assert not CommentReaction.objects.filter(comment=comment).exists()


@pytest.mark.contract
class TestPublicBoardOtherWorkspace:
    @pytest.mark.django_db
    def test_board_of_other_workspace_cannot_touch_issue(self, scenario):
        other_ws = Workspace.objects.create(name="Outro", owner=scenario["owner"], slug=f"outro-{uuid4().hex[:6]}")
        other_project = make_project(other_ws, scenario["owner"], "Outro publicado", "OUT")
        other_board = DeployBoard.objects.create(
            workspace=other_ws,
            project=other_project,
            entity_name="project",
            entity_identifier=other_project.id,
            is_comments_enabled=True,
            is_reactions_enabled=True,
            is_votes_enabled=True,
        )
        client = scenario["client"]
        issue = scenario["issue_a"]
        response = client.post(
            url(other_board.anchor, f"issues/{issue.id}/comments/"), {"comment_html": "<p>x</p>"}, format="json"
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND, detail(response)
        response = client.post(
            url(other_board.anchor, f"issues/{issue.id}/reactions/"), {"reaction": THUMBS_UP}, format="json"
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND, detail(response)
        response = client.post(url(other_board.anchor, f"issues/{issue.id}/votes/"), {"vote": 1}, format="json")
        assert response.status_code == status.HTTP_404_NOT_FOUND, detail(response)
        response = client.post(
            url(other_board.anchor, f"comments/{scenario['comment_a'].id}/reactions/"),
            {"reaction": THUMBS_UP},
            format="json",
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND, detail(response)

        assert not IssueComment.objects.filter(issue=issue, actor=scenario["visitor"]).exists()
        assert not IssueReaction.objects.filter(issue=issue).exists()
        assert not IssueVote.objects.filter(issue=issue).exists()
        assert not CommentReaction.objects.filter(comment=scenario["comment_a"]).exists()


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
    def test_list_returns_only_reactions_of_board_project(self, scenario):
        """A listagem funciona no chamado do board e não devolve a reação do chamado de outro projeto."""
        own = IssueReaction.objects.create(
            issue=scenario["issue_a"], project=scenario["project_a"], actor=scenario["owner"], reaction=THUMBS_UP
        )
        IssueReaction.objects.create(
            issue=scenario["issue_b"], project=scenario["project_b"], actor=scenario["owner"], reaction=THUMBS_UP
        )
        response = scenario["client"].get(url(scenario["anchor"], f"issues/{scenario['issue_a'].id}/reactions/"))
        assert response.status_code == status.HTTP_200_OK, detail(response)
        assert [str(r["id"]) for r in response.data] == [str(own.id)]

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
    def test_remove_own_reaction_on_comment_of_other_project_is_404(self, scenario):
        reaction = CommentReaction.objects.create(
            comment=scenario["comment_b"], project=scenario["project_b"], actor=scenario["visitor"], reaction=THUMBS_UP
        )
        response = scenario["client"].delete(
            url(scenario["anchor"], f"comments/{scenario['comment_b'].id}/reactions/{THUMBS_UP}/")
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND, detail(response)
        reaction.refresh_from_db()
        assert reaction.deleted_at is None

    @pytest.mark.django_db
    def test_remove_own_reaction_on_comment_of_board_project_works(self, scenario):
        CommentReaction.objects.create(
            comment=scenario["comment_a"], project=scenario["project_a"], actor=scenario["visitor"], reaction=THUMBS_UP
        )
        response = scenario["client"].delete(
            url(scenario["anchor"], f"comments/{scenario['comment_a'].id}/reactions/{THUMBS_UP}/")
        )
        assert response.status_code == status.HTTP_204_NO_CONTENT, detail(response)

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
    def asset(self, scenario, created_by=None, entity_type=FileAsset.EntityTypeContext.COMMENT_DESCRIPTION):
        asset = FileAsset.objects.create(
            attributes={"name": "print.png", "type": "image/png", "size": 10},
            asset=f"{scenario['project_a'].workspace_id}/{uuid4().hex}-print.png",
            size=10,
            workspace=scenario["project_a"].workspace,
            project=scenario["project_a"],
            entity_type=entity_type,
        )
        # O save() do modelo preenche created_by pelo usuário da requisição (vazio fora dela).
        FileAsset.objects.filter(pk=asset.pk).update(created_by=created_by or scenario["visitor"])
        asset.refresh_from_db()
        return asset

    def own_comment(self, scenario):
        return scenario["external_comment"](scenario["issue_a"], scenario["visitor"])

    def internal_comment(self, scenario):
        return IssueComment.objects.create(
            issue=scenario["issue_a"],
            project=scenario["project_a"],
            workspace=scenario["project_a"].workspace,
            comment_html="<p>nota interna</p>",
            access="INTERNAL",
            actor=scenario["visitor"],
        )

    def bulk(self, scenario, comment_id, asset_ids):
        return scenario["client"].post(
            f"/api/public/assets/v2/anchor/{scenario['anchor']}/{comment_id}/bulk/",
            {"asset_ids": [str(a) for a in asset_ids]},
            format="json",
        )

    def upload(self, scenario, comment_id):
        with mock.patch("plane.space.views.asset.S3Storage") as storage:
            storage.return_value.generate_presigned_post.return_value = {"url": "https://s3.test", "fields": {}}
            return scenario["client"].post(
                f"/api/public/assets/v2/anchor/{scenario['anchor']}/",
                {
                    "name": "print.png",
                    "type": "image/png",
                    "size": 10,
                    "entity_type": FileAsset.EntityTypeContext.COMMENT_DESCRIPTION,
                    "entity_identifier": str(comment_id),
                },
                format="json",
            )

    # vínculo em lote
    @pytest.mark.django_db
    def test_bulk_link_to_comment_of_other_project_is_404(self, scenario):
        asset = self.asset(scenario)
        own_in_b = scenario["external_comment"](scenario["issue_b"], scenario["visitor"])
        response = self.bulk(scenario, own_in_b.id, [asset.id])
        assert response.status_code == status.HTTP_404_NOT_FOUND, detail(response)
        asset.refresh_from_db()
        assert asset.comment_id is None

    @pytest.mark.django_db
    def test_bulk_link_to_comment_of_other_person_is_404(self, scenario):
        asset = self.asset(scenario)
        response = self.bulk(scenario, scenario["comment_a"].id, [asset.id])
        assert response.status_code == status.HTTP_404_NOT_FOUND, detail(response)
        asset.refresh_from_db()
        assert asset.comment_id is None

    @pytest.mark.django_db
    def test_bulk_link_to_internal_comment_is_404(self, scenario):
        asset = self.asset(scenario)
        response = self.bulk(scenario, self.internal_comment(scenario).id, [asset.id])
        assert response.status_code == status.HTTP_404_NOT_FOUND, detail(response)
        asset.refresh_from_db()
        assert asset.comment_id is None

    @pytest.mark.django_db
    def test_bulk_links_only_own_assets_and_leaves_others_untouched(self, scenario):
        """Ids de terceiros ou de descrição de chamado no meio do lote não são tocados."""
        mine = self.asset(scenario)
        theirs = self.asset(scenario, created_by=scenario["owner"])
        description = self.asset(scenario, entity_type=FileAsset.EntityTypeContext.ISSUE_DESCRIPTION)
        their_comment = scenario["external_comment"](scenario["issue_a"], scenario["owner"])
        FileAsset.objects.filter(pk=theirs.pk).update(comment=their_comment)
        comment = self.own_comment(scenario)

        response = self.bulk(scenario, comment.id, [mine.id, theirs.id, description.id])
        assert response.status_code == status.HTTP_204_NO_CONTENT, detail(response)
        mine.refresh_from_db()
        theirs.refresh_from_db()
        description.refresh_from_db()
        assert mine.comment_id == comment.id
        assert theirs.comment_id == their_comment.id
        assert description.comment_id is None

    @pytest.mark.django_db
    def test_bulk_with_image_removed_in_editor_links_the_rest(self, scenario):
        """O editor do board manda também o id da imagem que o visitante apagou antes de publicar."""
        kept = self.asset(scenario)
        removed = self.asset(scenario)
        removed.delete()
        comment = self.own_comment(scenario)

        response = self.bulk(scenario, comment.id, [kept.id, removed.id])
        assert response.status_code == status.HTTP_204_NO_CONTENT, detail(response)
        kept.refresh_from_db()
        assert kept.comment_id == comment.id
        assert FileAsset.all_objects.get(pk=removed.pk).comment_id is None

    @pytest.mark.django_db
    def test_bulk_link_own_assets_to_own_comment_works(self, scenario):
        assets = [self.asset(scenario), self.asset(scenario)]
        comment = self.own_comment(scenario)
        response = self.bulk(scenario, comment.id, [a.id for a in assets])
        assert response.status_code == status.HTTP_204_NO_CONTENT, detail(response)
        for asset in assets:
            asset.refresh_from_db()
            assert asset.comment_id == comment.id

    # upload
    @pytest.mark.django_db
    def test_upload_for_comment_of_other_project_is_404(self, scenario):
        own_in_b = scenario["external_comment"](scenario["issue_b"], scenario["visitor"])
        response = self.upload(scenario, own_in_b.id)
        assert response.status_code == status.HTTP_404_NOT_FOUND, detail(response)
        assert not FileAsset.objects.filter(comment=own_in_b).exists()

    @pytest.mark.django_db
    def test_upload_for_comment_of_other_person_is_404(self, scenario):
        response = self.upload(scenario, scenario["comment_a"].id)
        assert response.status_code == status.HTTP_404_NOT_FOUND, detail(response)
        assert not FileAsset.objects.filter(comment=scenario["comment_a"]).exists()

    @pytest.mark.django_db
    def test_upload_for_internal_comment_is_404(self, scenario):
        internal = self.internal_comment(scenario)
        response = self.upload(scenario, internal.id)
        assert response.status_code == status.HTTP_404_NOT_FOUND, detail(response)
        assert not FileAsset.objects.filter(comment=internal).exists()

    @pytest.mark.django_db
    def test_upload_for_own_comment_works(self, scenario):
        comment = self.own_comment(scenario)
        response = self.upload(scenario, comment.id)
        assert response.status_code == status.HTTP_200_OK, detail(response)
        assert FileAsset.objects.filter(comment=comment, created_by=scenario["visitor"]).exists()
