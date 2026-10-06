# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""MCP writes record activity, so they reach the history, notifications and the chat room."""

import json
from unittest import mock

import pytest

from plane.db.models import Issue, IssueComment, Project, ProjectMember, State, User
from plane.mcp.tools import handlers


@pytest.fixture
def project(db, workspace, create_user):
    project = Project.objects.create(name="Manutenção", identifier="MAN", workspace=workspace, created_by=create_user)
    ProjectMember.objects.create(project=project, member=create_user, role=20, is_active=True)
    todo = State.objects.create(name="A fazer", group="unstarted", project=project, workspace=workspace, default=True)
    project.default_state = todo
    project.save()
    return project


@pytest.fixture
def activity():
    with mock.patch("plane.bgtasks.issue_activities_task.issue_activity.delay") as delay:
        yield delay


@pytest.mark.contract
class TestMCPActivity:
    def test_create_records_created_activity_by_the_bot(self, workspace, project, create_user, activity):
        result = handlers.create_work_item(workspace.slug, "MAN", "Corrigir login", assignee_ids=[str(create_user.id)])

        issue = Issue.objects.get(pk=result["id"])
        bot = User.objects.get(username=handlers.MCP_BOT_USERNAME)
        assert bot.is_bot and issue.created_by_id == bot.id
        kwargs = activity.call_args.kwargs
        assert kwargs["type"] == "issue.activity.created"
        assert kwargs["actor_id"] == str(bot.id)
        assert json.loads(kwargs["requested_data"])["assignee_ids"] == [str(create_user.id)]

    def test_update_records_only_changed_fields(self, workspace, project, activity):
        result = handlers.create_work_item(workspace.slug, "MAN", "Corrigir login")
        doing = State.objects.create(name="Em andamento", group="started", project=project, workspace=workspace)
        activity.reset_mock()

        handlers.update_work_item(workspace.slug, result["id"], state_id=str(doing.id), name="Corrigir login")

        kwargs = activity.call_args.kwargs
        assert kwargs["type"] == "issue.activity.updated"
        assert json.loads(kwargs["requested_data"]) == {"state_id": str(doing.id)}
        assert json.loads(kwargs["current_instance"]) == {"state_id": str(project.default_state_id)}

    def test_update_without_changes_records_nothing(self, workspace, project, activity):
        result = handlers.create_work_item(workspace.slug, "MAN", "Corrigir login")
        activity.reset_mock()
        handlers.update_work_item(workspace.slug, result["id"], name="Corrigir login")
        activity.assert_not_called()

    def test_comment_records_comment_activity(self, workspace, project, activity):
        result = handlers.create_work_item(workspace.slug, "MAN", "Corrigir login")
        activity.reset_mock()

        handlers.add_work_item_comment(workspace.slug, result["id"], "<p>Feito</p>")

        comment = IssueComment.objects.get(issue_id=result["id"])
        assert comment.actor.username == handlers.MCP_BOT_USERNAME
        assert activity.call_args.kwargs["type"] == "comment.activity.created"
