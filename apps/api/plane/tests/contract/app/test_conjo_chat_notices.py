# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Chat notices (MAN-209): m.notice with a structured card payload, edits within 10 min, batch moves."""

from types import SimpleNamespace
from unittest import mock

import pytest
from django.core.cache import cache

from plane.bgtasks import conjo_chat_task
from plane.bgtasks.conjo_chat_task import NOTICE_KEY, build_fragment, flush_chat_batch, notify_chat_room
from plane.bgtasks.conjo_github_task import notify_chat_pull_request
from plane.db.models import (
    Intake,
    IntakeIssue,
    Issue,
    IssueComment,
    IssueLabel,
    Label,
    Project,
    ProjectChatIntegration,
    State,
    User,
)
from plane.utils import conjo_chat
from plane.utils.conjo_chat import MatrixError

ROOM = "!sala:chat.conjosa.com.br"
TASKS = "https://tasks.conjosa.com.br"
PR = {
    "number": 7,
    "title": "MAN-1 corrige login",
    "url": "https://github.com/Conjo-SA/app/pull/7",
    "repository": "Conjo-SA/app",
    "author": "andre",
}


@pytest.fixture(autouse=True)
def chat_settings(settings):
    settings.CONJO_CHAT_HOMESERVER_URL = "https://chat.conjosa.com.br"
    settings.CONJO_CHAT_BOT_PASSWORD = "x"
    settings.TASKS_PUBLIC_URL = TASKS
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def matrix():
    """Record what would go to the homeserver; every send answers a new event id."""
    sent = []

    def request(method, path, json=None):
        sent.append({"method": method, "path": path, "json": json})
        return {"event_id": f"$ev{len(sent)}"}

    with mock.patch.object(conjo_chat, "matrix_request", side_effect=request):
        yield sent


@pytest.fixture
def project(db, workspace, create_user):
    project = Project.objects.create(name="Manutenção", identifier="MAN", workspace=workspace, created_by=create_user)
    ProjectChatIntegration.objects.create(project=project, workspace=workspace, enabled=True, room_id=ROOM)
    return project


@pytest.fixture
def states(project):
    def make(name, group, seq):
        return State.objects.create(name=name, group=group, sequence=seq, project=project, workspace=project.workspace)

    return {
        "triage": State.objects.create(name="Triagem", group="triage", project=project, workspace=project.workspace),
        "todo": make("A fazer", "unstarted", 1),
        "review": make("Em revisão", "started", 2),
        "gmud": make("Aprovado p/ GMUD", "completed", 3),
    }


@pytest.fixture
def actor(create_user):
    create_user.first_name, create_user.last_name = "Ana", "Lima"
    create_user.save()
    return create_user


def make_issue(project, **kwargs):
    defaults = {"name": "Ajuste na modal de categorias", "project": project, "priority": "high"}
    defaults.update(kwargs)
    return Issue.objects.create(**defaults)


def move(old, new, txn="t-move"):
    return {
        "kind": "state",
        "old": old.name,
        "new": new.name,
        "old_id": str(old.id),
        "new_id": str(new.id),
        "txn_id": txn,
        "at": "2026-10-09T12:00:00+00:00",
    }


def content_of(call):
    return call["json"]


@pytest.mark.contract
class TestNoticeContract:
    def test_moved(self, project, states, actor, matrix):
        issue = make_issue(project)
        notify_chat_room(str(project.id), str(issue.id), str(actor.id), [move(states["todo"], states["review"])])

        assert len(matrix) == 1
        call = matrix[0]
        # Idempotent resend: the event's txn_id is the Matrix transaction id.
        assert call["method"] == "PUT" and call["path"].endswith("/send/m.room.message/t-move")
        content = content_of(call)
        assert content["msgtype"] == "m.notice"
        assert content["format"] == "org.matrix.custom.html"
        url = f"{TASKS}/test-workspace/browse/MAN-{issue.sequence_id}/"
        key = f"MAN-{issue.sequence_id}"
        assert content["body"] == (
            f"{key} Ajuste na modal de categorias\nAna Lima moveu de A fazer para Em revisão\n{url}"
        )
        assert content["formatted_body"].startswith(
            f'<a href="{url}"><b>{key}</b></a> Ajuste na modal de categorias<br>'
        )
        assert '<font data-mx-color="#f59e0b">● Em revisão</font>' in content["formatted_body"]
        assert content[NOTICE_KEY] == {
            "v": 1,
            "kind": "moved",
            "issues": [{"key": key, "title": "Ajuste na modal de categorias", "url": url}],
            "actor": {"name": "Ana Lima", "is_bot": False},
            "from": {"name": "A fazer", "group": "unstarted"},
            "to": {"name": "Em revisão", "group": "started"},
            "quote": None,
            "chips": [],
            "steps": [
                {
                    "text": "Ana Lima moveu de A fazer para Em revisão",
                    "at": "2026-10-09T12:00:00+00:00",
                    "kind": "moved",
                }
            ],
            "cta": {"label": "Abrir no Tasks", "url": url},
            "at": "2026-10-09T12:00:00+00:00",
        }
        # Explicitly no mentions: does not rely on the push rules for m.notice.
        assert content["m.mentions"] == {}

    def test_commented_escapes_title_and_comment(self, project, actor, matrix):
        issue = make_issue(project, name="<script>alert(1)</script> título")
        comment = IssueComment.objects.create(
            issue=issue,
            project=project,
            actor=actor,
            comment_html="<p>1 &lt; 2 &amp;&amp; x</p>",
            comment_stripped="1 < 2 && x",
        )
        notify_chat_room(
            str(project.id),
            str(issue.id),
            str(actor.id),
            [{"kind": "comment", "comment_id": str(comment.id), "txn_id": "t1"}],
        )

        content = content_of(matrix[0])
        html = content["formatted_body"]
        assert "<script>" not in html and "&lt;script&gt;alert(1)&lt;/script&gt; título" in html
        assert "<blockquote>1 &lt; 2 &amp;&amp; x</blockquote>" in html
        notice = content[NOTICE_KEY]
        assert notice["kind"] == "commented"
        assert notice["issues"][0]["title"] == "<script>alert(1)</script> título"
        assert notice["quote"] == "1 < 2 && x"
        assert notice["cta"]["label"] == "Responder"
        assert content["body"].splitlines()[1] == "Ana Lima comentou"

    def test_mcp_writes_are_the_assistant_bot(self, project, states, matrix):
        bot = User.objects.create(
            username="conjo_mcp_bot",
            email="mcp-bot@tasks.local",
            first_name="Assistente",
            last_name="(MCP)",
            display_name="Assistente (MCP)",
            is_bot=True,
        )
        issue = make_issue(project)
        notify_chat_room(str(project.id), str(issue.id), str(bot.id), [move(states["todo"], states["gmud"])])

        notice = content_of(matrix[0])[NOTICE_KEY]
        assert notice["actor"] == {"name": "Assistente", "is_bot": True}
        assert notice["to"] == {"name": "Aprovado p/ GMUD", "group": "completed"}
        assert '<font data-mx-color="#16a34a">● Aprovado p/ GMUD</font>' in content_of(matrix[0])["formatted_body"]

    def test_created_assigned_and_unassigned(self, project, actor, matrix):
        issue = make_issue(project)
        other = User.objects.create(username="bia", email="bia@x.com", first_name="Bia", last_name="Reis")
        notify_chat_room(str(project.id), str(issue.id), str(actor.id), [{"kind": "created", "txn_id": "c"}])
        notify_chat_room(
            str(project.id),
            str(issue.id),
            str(actor.id),
            [{"kind": "assignee_added", "user_id": str(other.id), "txn_id": "a"}],
        )
        notify_chat_room(
            str(project.id),
            str(issue.id),
            str(actor.id),
            [{"kind": "assignee_removed", "user_id": str(other.id), "txn_id": "r"}],
        )

        assert content_of(matrix[0])[NOTICE_KEY]["kind"] == "created"
        assert content_of(matrix[0])["body"].splitlines()[1] == "Ana Lima criou o card"
        # Same card within the window: edits of the first message.
        assert content_of(matrix[1])["m.new_content"][NOTICE_KEY]["kind"] == "assigned"
        last = content_of(matrix[2])["m.new_content"][NOTICE_KEY]
        assert last["kind"] == "unassigned"
        assert [step["text"] for step in last["steps"]] == [
            "Ana Lima criou o card",
            "Ana Lima atribuiu a Bia Reis",
            "Ana Lima removeu Bia Reis",
        ]

    def test_pull_request_kinds(self, project, matrix):
        issue = make_issue(project)
        for kind, txn in (("opened", "p1"), ("closed", "p2")):
            notify_chat_pull_request(str(project.id), str(issue.id), kind, PR, txn)

        opened = content_of(matrix[0])
        assert opened[NOTICE_KEY]["kind"] == "pr_opened"
        assert opened[NOTICE_KEY]["cta"] == {"label": "Ver PR #7", "url": PR["url"]}
        assert opened[NOTICE_KEY]["chips"] == ["Conjo-SA/app"]
        assert opened[NOTICE_KEY]["actor"] == {"name": "andre", "is_bot": False}
        assert f'<a href="{PR["url"]}">PR #7</a>' in opened["formatted_body"]
        closed = content_of(matrix[1])["m.new_content"][NOTICE_KEY]
        assert closed["kind"] == "pr_closed"
        assert closed["steps"][-1]["text"] == "andre fechou sem merge o PR #7 MAN-1 corrige login em Conjo-SA/app"

    def test_non_https_links_are_dropped(self, project, matrix):
        issue = make_issue(project)
        notify_chat_pull_request(str(project.id), str(issue.id), "opened", {**PR, "url": "javascript:alert(1)"}, "p")
        content = content_of(matrix[0])
        assert content[NOTICE_KEY]["cta"] == {
            "label": "Abrir no Tasks",
            "url": f"{TASKS}/test-workspace/browse/MAN-{issue.sequence_id}/",
        }
        assert "javascript:" not in content["formatted_body"]


@pytest.mark.contract
class TestIntakeNotice:
    def test_portal_request_has_client_data_and_tags_everyone(self, workspace, project, matrix):
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

        notify_chat_room(str(project.id), str(issue.id), None, [{"kind": "created", "txn_id": "i1"}])

        content = content_of(matrix[0])
        html = content["formatted_body"]
        # @room only notifies from a regular message (m.notice is silenced by the default push rules).
        assert content["msgtype"] == "m.text"
        assert content["m.mentions"] == {"room": True}
        assert "Nova solicitação na Entrada" in html and "Alguém" not in html
        assert "<b>Cliente:</b> Maria Souza (maria@cliente.com.br)" in html
        assert "<b>Prioridade:</b> Alta" in html and "<b>Etiqueta:</b> LTQ" in html
        assert "<blockquote>Ao lançar uma receita a modal não filtra.</blockquote>" in html
        assert html.endswith("@room") and content["body"].endswith("@room")
        notice = content[NOTICE_KEY]
        assert notice["kind"] == "intake"
        assert notice["actor"] == {"name": "Maria Souza", "is_bot": False}
        assert notice["chips"] == ["Cliente: Maria Souza (maria@cliente.com.br)", "Prioridade: Alta", "Etiqueta: LTQ"]

    def test_regular_card_keeps_the_short_notice(self, workspace, project):
        issue = make_issue(project)
        frag = build_fragment({"kind": "created"}, {"name": "Ana", "is_bot": False}, issue, workspace.slug)
        assert frag["mention_room"] is False and frag["msgtype"] == "m.notice"
        assert frag["html"] == "<b>Ana</b> criou o card"

    def test_room_mention_is_sent_as_intentional_mention(self):
        with mock.patch.object(conjo_chat, "matrix_request") as request:
            conjo_chat.send_html_message("!r:x", "<b>oi</b> @room", "oi @room", txn_id="t1", mention_room=True)
        assert request.call_args.kwargs["json"]["m.mentions"] == {"room": True}
        with mock.patch.object(conjo_chat, "matrix_request") as request:
            conjo_chat.send_html_message("!r:x", "oi", "oi", txn_id="t2")
        assert "m.mentions" not in request.call_args.kwargs["json"]


@pytest.mark.contract
class TestGrouping:
    def test_pr_opened_merged_and_moved_edit_one_message(self, project, states, actor, matrix):
        issue = make_issue(project)
        notify_chat_pull_request(str(project.id), str(issue.id), "opened", PR, "p1")
        notify_chat_pull_request(str(project.id), str(issue.id), "merged", PR, "p2")
        notify_chat_room(str(project.id), str(issue.id), str(actor.id), [move(states["review"], states["gmud"], "m1")])

        assert len(matrix) == 3
        assert "m.relates_to" not in content_of(matrix[0])
        for call, txn in ((matrix[1], "p2"), (matrix[2], "m1")):
            assert call["path"].endswith(f"/send/m.room.message/{txn}-edit-%24ev1")
            assert call["json"]["m.mentions"] == {}
            assert call["json"]["m.relates_to"] == {"rel_type": "m.replace", "event_id": "$ev1"}
            assert call["json"]["body"].startswith("* ")
            assert NOTICE_KEY not in call["json"]
        new = content_of(matrix[2])["m.new_content"]
        notice = new[NOTICE_KEY]
        assert notice["kind"] == "moved"
        assert [step["kind"] for step in notice["steps"]] == ["pr_opened", "pr_merged", "moved"]
        assert notice["actor"] == {"name": "Ana Lima", "is_bot": False}
        assert notice["to"] == {"name": "Aprovado p/ GMUD", "group": "completed"}
        # A plain move keeps the more useful "Ver PR" button.
        assert notice["cta"] == {"label": "Ver PR #7", "url": PR["url"]}
        assert new["msgtype"] == "m.notice"
        assert new["body"].splitlines()[1:4] == [
            "andre abriu o PR #7 MAN-1 corrige login em Conjo-SA/app",
            "andre mergeou o PR #7 MAN-1 corrige login em Conjo-SA/app",
            "Ana Lima moveu de Em revisão para Aprovado p/ GMUD",
        ]

    def test_new_message_after_the_window(self, project, states, actor, matrix):
        issue = make_issue(project)
        notify_chat_pull_request(str(project.id), str(issue.id), "opened", PR, "p1")
        key = conjo_chat_task.LAST_NOTICE_KEY.format(room_id=ROOM, issue_id=issue.id)
        last = cache.get(key)
        cache.set(key, {**last, "ts": last["ts"] - conjo_chat_task.GROUP_WINDOW - 1}, 600)

        notify_chat_room(str(project.id), str(issue.id), str(actor.id), [move(states["review"], states["gmud"], "m1")])

        assert len(matrix) == 2
        assert "m.relates_to" not in content_of(matrix[1])
        assert [step["kind"] for step in content_of(matrix[1])[NOTICE_KEY]["steps"]] == ["moved"]
        assert cache.get(key)["event_id"] == "$ev2"

    def test_other_cards_are_not_grouped(self, project, states, actor, matrix):
        first, second = make_issue(project), make_issue(project, name="Outro")
        notify_chat_room(str(project.id), str(first.id), str(actor.id), [move(states["todo"], states["review"], "a")])
        notify_chat_room(str(project.id), str(second.id), str(actor.id), [move(states["todo"], states["gmud"], "b")])
        assert all("m.relates_to" not in call["json"] for call in matrix)

    def test_failed_edit_falls_back_to_a_new_message(self, project, states, actor):
        issue = make_issue(project)
        sent = []

        def request(method, path, json=None):
            sent.append({"path": path, "json": json})
            if "m.relates_to" in (json or {}):
                raise MatrixError("Matrix error 400 M_BAD_JSON: nope", status_code=400)
            return {"event_id": f"$ev{len(sent)}"}

        with mock.patch.object(conjo_chat, "matrix_request", side_effect=request):
            notify_chat_pull_request(str(project.id), str(issue.id), "opened", PR, "p1")
            notify_chat_room(
                str(project.id), str(issue.id), str(actor.id), [move(states["review"], states["gmud"], "m1")]
            )

        assert len(sent) == 3
        fallback = sent[2]
        assert fallback["path"].endswith("/send/m.room.message/m1-new")
        assert "m.relates_to" not in fallback["json"]
        assert fallback["json"][NOTICE_KEY]["kind"] == "moved"
        # The new message becomes the one later events edit.
        key = conjo_chat_task.LAST_NOTICE_KEY.format(room_id=ROOM, issue_id=issue.id)
        assert cache.get(key)["event_id"] == "$ev3"


def activity(old, new):
    return SimpleNamespace(
        field="state",
        verb="updated",
        old_value=old.name,
        new_value=new.name,
        old_identifier=old.id,
        new_identifier=new.id,
        issue_comment_id=None,
    )


@pytest.mark.contract
class TestBatchMove:
    def test_same_actor_same_state_posts_one_notice(self, project, states, actor, matrix):
        issues = [make_issue(project, name=f"Card {n}") for n in range(3)]
        with (
            mock.patch.object(conjo_chat_task.flush_chat_batch, "apply_async") as flush,
            mock.patch.object(conjo_chat_task.notify_chat_room, "delay") as direct,
        ):
            for issue in issues:
                conjo_chat_task.enqueue_chat_notifications(
                    "issue.activity.updated", issue.id, actor.id, project.id, [activity(states["todo"], states["gmud"])]
                )
        assert direct.call_count == 0
        assert flush.call_count == 3
        assert flush.call_args.kwargs["countdown"] == conjo_chat_task.BATCH_WINDOW

        with mock.patch.object(conjo_chat_task.notify_chat_room, "delay") as delay:
            for call in flush.call_args_list:
                flush_chat_batch(*call.kwargs["args"])
        # The first flush takes the whole batch; the others find it empty.
        assert delay.call_count == 1
        args, kwargs = delay.call_args
        assert kwargs["batch_issue_ids"] == [str(issue.id) for issue in issues]

        notify_chat_room(*args, **kwargs)
        assert len(matrix) == 1
        content = content_of(matrix[0])
        notice = content[NOTICE_KEY]
        assert notice["kind"] == "moved"
        assert [item["title"] for item in notice["issues"]] == ["Card 0", "Card 1", "Card 2"]
        assert notice["steps"][0]["text"] == "Ana Lima moveu 3 cards de A fazer para Aprovado p/ GMUD"
        assert notice["from"] == {"name": "A fazer", "group": "unstarted"}
        assert content["body"].splitlines()[:3] == ["MAN-1 Card 0", "MAN-2 Card 1", "MAN-3 Card 2"]

    def test_single_move_goes_through_the_card_notice(self, project, states, actor, matrix):
        issue = make_issue(project)
        with mock.patch.object(conjo_chat_task.flush_chat_batch, "apply_async") as flush:
            conjo_chat_task.enqueue_chat_notifications(
                "issue.activity.updated", issue.id, actor.id, project.id, [activity(states["todo"], states["review"])]
            )
        with mock.patch.object(conjo_chat_task.notify_chat_room, "delay") as delay:
            flush_chat_batch(*flush.call_args.kwargs["args"])
        assert delay.call_args.kwargs["batch_issue_ids"] is None
        notify_chat_room(*delay.call_args.args, **delay.call_args.kwargs)
        assert content_of(matrix[0])[NOTICE_KEY]["issues"][0]["title"] == issue.name


@pytest.mark.contract
class TestHardening:
    def test_batch_ignores_cards_of_other_projects(self, workspace, project, states, actor, matrix):
        ours = [make_issue(project, name="Nosso 1"), make_issue(project, name="Nosso 2")]
        other_project = Project.objects.create(name="Outro", identifier="OUT", workspace=workspace)
        foreign = make_issue(other_project, name="Segredo de outro projeto")
        ids = [str(item.id) for item in (*ours, foreign)]
        events = [move(states["todo"], states["gmud"], f"t{n}") for n in range(3)]

        notify_chat_room(str(project.id), ids[0], str(actor.id), events, batch_issue_ids=ids)

        notice = content_of(matrix[0])[NOTICE_KEY]
        assert [item["title"] for item in notice["issues"]] == ["Nosso 1", "Nosso 2"]
        assert "Segredo" not in content_of(matrix[0])["body"] + content_of(matrix[0])["formatted_body"]

    def test_batch_lists_at_most_30_cards(self, project, states, actor, matrix):
        issues = [make_issue(project, name=f"Card {n} " + "x" * 200) for n in range(32)]
        ids = [str(item.id) for item in issues]
        events = [move(states["todo"], states["gmud"], f"t{n}") for n in range(32)]

        notify_chat_room(str(project.id), ids[0], str(actor.id), events, batch_issue_ids=ids)

        content = content_of(matrix[0])
        notice = content[NOTICE_KEY]
        assert len(notice["issues"]) == conjo_chat_task.MAX_BATCH_ISSUES == 30
        assert notice["chips"] == ["+2 cards"]
        assert notice["steps"][0]["text"].startswith("Ana Lima moveu 32 cards")
        assert "+2 cards" in content["formatted_body"] and "+2 cards" in content["body"]
        assert conjo_chat_task.content_size(content) <= conjo_chat_task.MAX_CONTENT_BYTES
        assert content["m.mentions"] == {}

    def test_oversized_notice_drops_oldest_steps(self):
        steps = [
            {"text": f"passo {n} " + "y" * 1000, "at": "2026-10-09T12:00:00+00:00", "kind": "moved"} for n in range(80)
        ]
        notice = {
            "v": 1,
            "kind": "moved",
            "issues": [{"key": "MAN-1", "title": "t", "url": f"{TASKS}/x/browse/MAN-1/"}],
            "actor": {"name": "Ana", "is_bot": False},
            "from": None,
            "to": None,
            "quote": None,
            "chips": [],
            "steps": steps,
            "cta": None,
            "at": "2026-10-09T12:00:00+00:00",
        }
        content = conjo_chat_task.build_content(notice, "<b>Ana</b> moveu")
        assert conjo_chat_task.content_size(content) <= conjo_chat_task.MAX_CONTENT_BYTES
        kept = content[NOTICE_KEY]["steps"]
        assert 1 <= len(kept) < 80 and kept[-1]["text"].startswith("passo 79 ")

    def test_too_large_refusal_is_logged_not_raised(self, project, states, actor):
        issue = make_issue(project)

        def refuse(method, path, json=None):
            raise MatrixError("Matrix error 413 M_TOO_LARGE: event too large", status_code=413, errcode="M_TOO_LARGE")

        with (
            mock.patch.object(conjo_chat, "matrix_request", side_effect=refuse),
            mock.patch.object(conjo_chat_task.logger, "warning") as warning,
            mock.patch.object(conjo_chat_task, "log_exception") as logged,
        ):
            notify_chat_room(str(project.id), str(issue.id), str(actor.id), [move(states["todo"], states["review"])])
        assert "too large" in warning.call_args.args[0]
        assert logged.call_count == 0

    def test_edits_never_mention_but_keep_the_full_content(self, workspace, project, states, actor, matrix):
        issue = make_issue(project)
        intake = Intake.objects.create(name="Entrada", project=project)
        IntakeIssue.objects.create(intake=intake, project=project, issue=issue, source="PORTAL", source_email="a@b.c")
        notify_chat_room(str(project.id), str(issue.id), None, [{"kind": "created", "txn_id": "i1"}])
        notify_chat_room(str(project.id), str(issue.id), str(actor.id), [move(states["todo"], states["review"])])

        assert content_of(matrix[0])["m.mentions"] == {"room": True}
        edit = content_of(matrix[1])
        assert edit["m.mentions"] == {}
        assert edit["m.new_content"]["m.mentions"] == {"room": True}
