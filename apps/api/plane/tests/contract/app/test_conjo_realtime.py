# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Realtime: publishing work item changes to the live server and who may join a project's room."""

import json
from unittest import mock
from uuid import uuid4

import pytest
from rest_framework.test import APIClient

from plane.bgtasks.issue_activities_task import issue_activity
from plane.db.models import Issue, Project, ProjectMember, State, User, WorkspaceMember
from plane.utils import realtime

ACCESS_URL = "/api/workspaces/{slug}/projects/{project_id}/realtime-access/"


@pytest.fixture
def project(db, workspace, create_user):
    project = Project.objects.create(name="Manutenção", identifier="MAN", workspace=workspace, created_by=create_user)
    ProjectMember.objects.create(project=project, member=create_user, workspace=workspace, role=20, is_active=True)
    todo = State.objects.create(name="A fazer", group="unstarted", project=project, workspace=workspace, default=True)
    project.default_state = todo
    project.save()
    return project


def _user(workspace, role):
    unique_id = uuid4().hex[:8]
    user = User.objects.create(email=f"u-{unique_id}@conjo.com.br", username=f"u_{unique_id}")
    WorkspaceMember.objects.create(workspace=workspace, member=user, role=role)
    return user


def _client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def no_redis():
    """Redis unavailable: exercises the HTTP fallback to the live server."""
    with mock.patch("plane.utils.realtime._publish_redis", return_value=False):
        yield


@pytest.fixture
def secret(monkeypatch, no_redis):
    monkeypatch.setenv("LIVE_SERVER_SECRET_KEY", "s3cr3t")
    monkeypatch.delenv("LIVE_INTERNAL_URL", raising=False)
    return "s3cr3t"


@pytest.mark.unit
class TestPublishHelper:
    def test_redis_is_used_first_without_any_secret(self, monkeypatch):
        """Workers share the internal Redis with the live server: no secret needed, no HTTP hop."""
        monkeypatch.delenv("LIVE_SERVER_SECRET_KEY", raising=False)
        fake = mock.Mock()
        with (
            mock.patch("plane.settings.redis.redis_instance", return_value=fake),
            mock.patch("plane.utils.realtime.requests.post") as post,
        ):
            assert realtime.send_event({"type": "issue.updated", "issue_ids": ["x"]}) is True
        channel, message = fake.publish.call_args.args
        assert channel == "tasks:realtime:events"
        assert json.loads(message) == {"type": "issue.updated", "issue_ids": ["x"]}
        post.assert_not_called()

    def test_send_event_posts_to_live_with_secret_and_short_timeout(self, secret):
        with mock.patch("plane.utils.realtime.requests.post") as post:
            post.return_value.status_code = 202
            assert realtime.send_event({"type": "issue.updated"}) is True
        args, kwargs = post.call_args
        assert args[0] == "http://live:3000/live/realtime/publish"
        assert kwargs["headers"] == {"live-server-secret-key": "s3cr3t"}
        assert kwargs["timeout"] <= 1.0

    def test_internal_url_is_configurable(self, secret, monkeypatch):
        monkeypatch.setenv("LIVE_INTERNAL_URL", "http://tasks-live:3100/")
        with mock.patch("plane.utils.realtime.requests.post") as post:
            post.return_value.status_code = 202
            realtime.send_event({"type": "issue.updated"})
        assert post.call_args.args[0] == "http://tasks-live:3100/live/realtime/publish"

    def test_without_redis_and_secret_nothing_is_sent(self, monkeypatch, no_redis):
        monkeypatch.delenv("LIVE_SERVER_SECRET_KEY", raising=False)
        with mock.patch("plane.utils.realtime.requests.post") as post:
            assert realtime.send_event({"type": "issue.updated"}) is False
            realtime.publish_project_event("issue.updated", str(uuid4()), [str(uuid4())], background=False)
        post.assert_not_called()

    def test_failures_never_raise(self, secret):
        with mock.patch("plane.utils.realtime.requests.post", side_effect=OSError("down")):
            assert realtime.send_event({"type": "issue.updated"}) is False

    @pytest.mark.django_db
    def test_event_carries_only_ids_and_is_sent_after_commit(
        self, secret, workspace, project, create_user, django_capture_on_commit_callbacks
    ):
        issue = Issue.objects.create(name="Segredo do cliente", project=project, workspace=workspace)
        with mock.patch("plane.utils.realtime.requests.post") as post:
            post.return_value.status_code = 202
            with django_capture_on_commit_callbacks(execute=False) as callbacks:
                realtime.publish_project_event(
                    "issue.updated", project.id, [issue.id], create_user.id, ["state_id"], background=False
                )
            post.assert_not_called()
            for callback in callbacks:
                callback()
        payload = post.call_args.kwargs["json"]
        assert payload["type"] == "issue.updated"
        assert payload["workspace_slug"] == workspace.slug
        assert payload["project_id"] == str(project.id)
        assert payload["issue_ids"] == [str(issue.id)]
        assert payload["actor_id"] == str(create_user.id)
        assert payload["fields"] == ["state_id"]
        assert "Segredo" not in json.dumps(payload)


@pytest.mark.contract
class TestIssueActivityPublishes:
    def _run(self, **kwargs):
        defaults = dict(
            requested_data=json.dumps({}),
            current_instance=json.dumps({}),
            epoch=0,
            notification=False,
        )
        defaults.update(kwargs)
        with (
            mock.patch("plane.bgtasks.issue_activities_task.publish_project_event") as publish,
            mock.patch("plane.bgtasks.issue_activities_task.enqueue_chat_notifications"),
        ):
            issue_activity(**defaults)
        return publish

    @pytest.mark.django_db
    def test_update_publishes_changed_fields(self, workspace, project, create_user):
        issue = Issue.objects.create(name="Corrigir login", project=project, workspace=workspace)
        publish = self._run(
            type="issue.activity.updated",
            requested_data=json.dumps({"sort_order": 1234.5, "priority": "high"}),
            current_instance=json.dumps({"sort_order": 65535, "priority": "none"}),
            issue_id=str(issue.id),
            actor_id=str(create_user.id),
            project_id=str(project.id),
        )
        kwargs = publish.call_args.kwargs
        assert kwargs["event_type"] == "issue.updated"
        assert kwargs["project_id"] == str(project.id)
        assert kwargs["issue_ids"] == [str(issue.id)]
        assert kwargs["actor_id"] == str(create_user.id)
        assert {"sort_order", "priority"} <= set(kwargs["fields"])

    @pytest.mark.django_db
    def test_comment_and_delete_publish(self, workspace, project, create_user):
        issue = Issue.objects.create(name="Corrigir login", project=project, workspace=workspace)
        publish = self._run(
            type="issue.activity.deleted",
            requested_data=json.dumps({"issue_id": str(issue.id)}),
            issue_id=str(issue.id),
            actor_id=str(create_user.id),
            project_id=str(project.id),
        )
        assert publish.call_args.kwargs["event_type"] == "issue.deleted"

    @pytest.mark.django_db
    def test_cycle_bulk_payload_lists_every_item(self, workspace, project, create_user):
        first = Issue.objects.create(name="A", project=project, workspace=workspace)
        second = Issue.objects.create(name="B", project=project, workspace=workspace)
        publish = self._run(
            type="cycle.activity.deleted",
            requested_data=json.dumps({"cycle_id": str(uuid4()), "issues": [str(first.id), str(second.id)]}),
            current_instance=json.dumps({"cycle_name": "Sprint"}),
            issue_id=None,
            actor_id=str(create_user.id),
            project_id=str(project.id),
        )
        assert set(publish.call_args.kwargs["issue_ids"]) == {str(first.id), str(second.id)}

    @pytest.mark.django_db
    def test_publish_failure_never_breaks_the_activity_log(self, workspace, project, create_user, secret):
        issue = Issue.objects.create(name="Corrigir login", project=project, workspace=workspace)
        with (
            mock.patch("plane.utils.realtime.requests.post", side_effect=OSError("down")),
            mock.patch("plane.bgtasks.issue_activities_task.enqueue_chat_notifications"),
            mock.patch("plane.bgtasks.issue_activities_task.log_exception") as log_exception,
        ):
            issue_activity(
                type="issue.activity.updated",
                requested_data=json.dumps({"priority": "high"}),
                current_instance=json.dumps({"priority": "none"}),
                issue_id=str(issue.id),
                actor_id=str(create_user.id),
                project_id=str(project.id),
                epoch=0,
            )
        log_exception.assert_not_called()


@pytest.mark.contract
class TestRealtimeAccess:
    @pytest.mark.django_db
    def test_member_may_join(self, session_client, workspace, project, create_user):
        response = session_client.get(ACCESS_URL.format(slug=workspace.slug, project_id=project.id))
        assert response.status_code == 200
        assert response.data == {"user_id": str(create_user.id), "project_id": str(project.id), "restricted": False}

    @pytest.mark.django_db
    def test_outsider_is_forbidden(self, workspace, project):
        outsider = _user(workspace, role=15)  # in the workspace, not in the project
        response = _client(outsider).get(ACCESS_URL.format(slug=workspace.slug, project_id=project.id))
        assert response.status_code == 403

    @pytest.mark.django_db
    def test_inactive_member_is_forbidden(self, workspace, project):
        former = _user(workspace, role=15)
        ProjectMember.objects.create(project=project, member=former, workspace=workspace, role=15, is_active=False)
        response = _client(former).get(ACCESS_URL.format(slug=workspace.slug, project_id=project.id))
        assert response.status_code == 403

    @pytest.mark.django_db
    def test_anonymous_is_rejected(self, workspace, project):
        response = APIClient().get(ACCESS_URL.format(slug=workspace.slug, project_id=project.id))
        assert response.status_code in (401, 403)

    @pytest.mark.django_db
    def test_guest_may_join_restricted_to_own_items(self, workspace, project):
        guest = _user(workspace, role=5)
        ProjectMember.objects.create(project=project, member=guest, workspace=workspace, role=5, is_active=True)
        response = _client(guest).get(ACCESS_URL.format(slug=workspace.slug, project_id=project.id))
        assert response.status_code == 200
        assert response.data["restricted"] is True

        project.guest_view_all_features = True
        project.save()
        response = _client(guest).get(ACCESS_URL.format(slug=workspace.slug, project_id=project.id))
        assert response.data["restricted"] is False


@pytest.mark.contract
class TestEndpointsOutsideTheActivityLog:
    @pytest.mark.django_db
    def test_bulk_delete_publishes(self, session_client, workspace, project, create_user):
        issue = Issue.objects.create(name="Duplicada", project=project, workspace=workspace)
        with mock.patch("plane.app.views.issue.base.publish_project_event") as publish:
            response = session_client.delete(
                f"/api/workspaces/{workspace.slug}/projects/{project.id}/bulk-delete-issues/",
                {"issue_ids": [str(issue.id)]},
                format="json",
            )
        assert response.status_code == 200
        args = publish.call_args.args
        assert args[0] == "issue.deleted"
        assert [str(issue_id) for issue_id in args[2]] == [str(issue.id)]

    @pytest.mark.django_db
    def test_issue_list_skips_recent_visit_for_realtime_refresh(self, session_client, workspace, project):
        issue = Issue.objects.create(name="A", project=project, workspace=workspace)
        url = f"/api/workspaces/{workspace.slug}/projects/{project.id}/issues/list/"
        with mock.patch("plane.app.views.issue.base.recent_visited_task.delay") as visit:
            response = session_client.get(url, {"issues": str(issue.id), "source": "realtime"})
        assert response.status_code == 200
        assert [row["id"] for row in response.data] == [issue.id]
        visit.assert_not_called()
