# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Chat notices: requests from the public form (Entrada) carry the client's data and tag the room."""

from unittest import mock

import pytest

from plane.bgtasks.conjo_chat_task import build_message
from plane.db.models import Intake, IntakeIssue, Issue, IssueLabel, Label, Project, State
from plane.utils import conjo_chat


@pytest.fixture
def project(db, workspace, create_user):
    project = Project.objects.create(name="Manutenção", identifier="MAN", workspace=workspace, created_by=create_user)
    State.objects.create(name="Triagem", group="triage", project=project, workspace=workspace)
    return project


def make_issue(project, **kwargs):
    defaults = {"name": "Ajuste na modal de categorias", "project": project, "priority": "high"}
    defaults.update(kwargs)
    return Issue.objects.create(**defaults)


@pytest.mark.contract
class TestIntakeNotice:
    def test_portal_request_has_client_data_and_tags_everyone(self, workspace, project):
        issue = make_issue(project, description_html="<p>Ao lançar uma receita a <b>modal</b> não filtra.</p>")
        intake = Intake.objects.create(name="Entrada", project=project)
        IntakeIssue.objects.create(
            intake=intake,
            project=project,
            issue=issue,
            source="PORTAL",
            source_email="maria@cliente.com.br",
            extra={"requester_name": "Maria Souza"},
        )
        label = Label.objects.create(name="LTQ", project=project)
        IssueLabel.objects.create(issue=issue, label=label, project=project)

        html, body, mention_room = build_message({"kind": "created"}, "Alguém", issue, workspace.slug)

        assert mention_room is True
        assert "Nova solicitação na Entrada" in html and "Alguém" not in html
        assert "Maria Souza (maria@cliente.com.br)" in html
        assert "<b>Prioridade:</b> Alta" in html and "<b>Etiqueta:</b> LTQ" in html
        assert "Ao lançar uma receita a modal não filtra." in html
        assert html.endswith("@room") and body.endswith("@room")

    def test_regular_card_keeps_the_short_notice(self, workspace, project):
        issue = make_issue(project)
        html, _body, mention_room = build_message({"kind": "created"}, "Ana", issue, workspace.slug)
        assert mention_room is False
        assert html.startswith("<b>Ana</b> criou")

    def test_room_mention_is_sent_as_intentional_mention(self):
        with mock.patch.object(conjo_chat, "matrix_request") as request:
            conjo_chat.send_html_message("!r:x", "<b>oi</b> @room", "oi @room", txn_id="t1", mention_room=True)
        assert request.call_args.kwargs["json"]["m.mentions"] == {"room": True}
        with mock.patch.object(conjo_chat, "matrix_request") as request:
            conjo_chat.send_html_message("!r:x", "oi", "oi", txn_id="t2")
        assert "m.mentions" not in request.call_args.kwargs["json"]
