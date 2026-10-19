# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""MAN-332: a resposta pública da equipe chega ao cliente com o texto e o botão do portal."""

from unittest import mock

import pytest
from django.test import override_settings

from plane.bgtasks.intake_portal_task import (
    _portal_ticket_url,
    send_portal_ticket_created,
    send_portal_ticket_reply,
)
from plane.bgtasks.issue_activities_task import notify_intake_portal_requester
from plane.db.models import (
    Intake,
    IntakeIssue,
    IntakePortal,
    Issue,
    IssueActivity,
    IssueComment,
    Project,
    ProjectMember,
    State,
    User,
)
from plane.db.models.intake import SourceType

EMAIL = "maria@cliente.com.br"
TASKS = "https://tasks.exemplo.com.br"
ONLY_TASKS_URL = {
    "SPACE_BASE_URL": None,
    "WEB_URL": None,
    "APP_BASE_URL": None,
    "TASKS_PUBLIC_URL": TASKS,
}


@pytest.fixture
def setup(db, workspace, create_user):
    project = Project.objects.create(name="Fretes", identifier="RSP", workspace=workspace, created_by=create_user)
    ProjectMember.objects.create(project=project, member=create_user, role=20, is_active=True)
    State.objects.create(name="Em andamento", group="started", project=project, workspace=workspace, default=True)
    intake = Intake.objects.create(name="Entrada", project=project, workspace=workspace)
    portal = IntakePortal.objects.create(project=project, workspace=workspace, intake=intake, is_enabled=True)
    issue = Issue.objects.create(name="Pedido de frete", project=project)
    # Chamado antigo: sem o identificador do portal gravado no `extra`.
    ticket = IntakeIssue.objects.create(
        project=project,
        workspace=workspace,
        intake=intake,
        issue=issue,
        source=SourceType.PORTAL,
        source_email=EMAIL,
        extra={"requester_name": "Maria"},
    )
    return {"project": project, "portal": portal, "issue": issue, "ticket": ticket, "user": create_user}


def comment(setup, access, html="<p>Olá Maria,</p><p>já ajustamos o frete.</p>", actor=None):
    return IssueComment.objects.create(
        issue=setup["issue"],
        project=setup["project"],
        workspace=setup["project"].workspace,
        comment_html=html,
        access=access,
        actor=actor or setup["user"],
    )


def outsider():
    return User.objects.create(email="curioso@fora.com", username="curioso")


def activity(setup, field, verb="created", comment_id=None):
    return IssueActivity(
        issue=setup["issue"],
        project=setup["project"],
        workspace=setup["project"].workspace,
        actor=setup["user"],
        field=field,
        verb=verb,
        issue_comment_id=comment_id,
    )


@override_settings(**ONLY_TASKS_URL)
def test_link_do_portal_usa_tasks_public_url_quando_nao_ha_outra_base():
    assert _portal_ticket_url("abc", "123") == f"{TASKS}/spaces/portal/abc/123"
    assert _portal_ticket_url("", "123") == ""


@override_settings(**ONLY_TASKS_URL)
def test_resposta_publica_vai_com_o_texto_e_o_botao(setup):
    reply = comment(
        setup, "EXTERNAL", "<p>Olá Maria,</p><p>já ajustamos <b>o frete</b> &amp; o prazo.</p><script>x()</script>"
    )
    with mock.patch("plane.bgtasks.intake_portal_task.send_transactional_email") as mail:
        send_portal_ticket_reply(str(setup["issue"].id), str(reply.id))
    to, subject, html = mail.call_args.args
    portal_url = f"{TASKS}/spaces/portal/{setup['portal'].anchor}/{setup['issue'].id}"
    assert to == EMAIL
    assert subject == "Nova resposta no seu chamado: Pedido de frete"
    assert "Olá Maria,\njá ajustamos o frete &amp; o prazo." in html and "&amp;amp;" not in html
    assert f'href="{portal_url}"' in html and "Ver e responder no portal" in html
    assert "<script>" not in html and "<b>" not in html


@override_settings(**ONLY_TASKS_URL)
def test_nota_interna_nunca_vira_e_mail(setup):
    note = comment(setup, "INTERNAL")
    with mock.patch("plane.bgtasks.intake_portal_task.send_transactional_email") as mail:
        send_portal_ticket_reply(str(setup["issue"].id), str(note.id))
    mail.assert_not_called()


@override_settings(**ONLY_TASKS_URL)
def test_chamado_recebido_tambem_ganha_o_botao(setup):
    with mock.patch("plane.bgtasks.intake_portal_task.send_transactional_email") as mail:
        send_portal_ticket_created(str(setup["issue"].id))
    html = mail.call_args.args[2]
    assert f"{TASKS}/spaces/portal/{setup['portal'].anchor}/{setup['issue'].id}" in html


def test_resposta_publica_dispara_o_e_mail_da_resposta_e_nota_interna_nada(setup):
    reply = comment(setup, "EXTERNAL")
    note = comment(setup, "INTERNAL")
    with (
        mock.patch("plane.bgtasks.intake_portal_task.send_portal_ticket_reply.delay") as reply_mail,
        mock.patch("plane.bgtasks.intake_portal_task.send_portal_ticket_update.delay") as update_mail,
    ):
        notify_intake_portal_requester(
            str(setup["issue"].id), str(setup["user"].id), [activity(setup, "comment", comment_id=note.id)]
        )
        reply_mail.assert_not_called()
        update_mail.assert_not_called()

        notify_intake_portal_requester(
            str(setup["issue"].id), str(setup["user"].id), [activity(setup, "comment", comment_id=reply.id)]
        )
        reply_mail.assert_called_once_with(str(setup["issue"].id), str(reply.id))
        update_mail.assert_not_called()

        # Mudança de status segue com o aviso de atualização.
        notify_intake_portal_requester(
            str(setup["issue"].id), str(setup["user"].id), [activity(setup, "state", verb="updated")]
        )
        update_mail.assert_called_once()
        assert "status" in update_mail.call_args.args[1]


@override_settings(**ONLY_TASKS_URL)
def test_comentario_publico_de_quem_nao_e_da_equipe_nao_vira_resposta(setup):
    stranger = comment(setup, "EXTERNAL", "<p>Pague o boleto em http://golpe.exemplo</p>", actor=outsider())
    with mock.patch("plane.bgtasks.intake_portal_task.send_transactional_email") as mail:
        send_portal_ticket_reply(str(setup["issue"].id), str(stranger.id))
    mail.assert_not_called()
    with mock.patch("plane.bgtasks.intake_portal_task.send_portal_ticket_reply.delay") as reply_mail:
        notify_intake_portal_requester(
            str(setup["issue"].id), str(stranger.actor_id), [activity(setup, "comment", comment_id=stranger.id)]
        )
    reply_mail.assert_not_called()
