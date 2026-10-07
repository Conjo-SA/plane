# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Board columns in Portuguese, and how long each card stayed in each column until done."""

import datetime
import importlib

import pytest
from django.apps import apps as django_apps
from django.utils import timezone
from rest_framework.test import APIClient

from plane.db.models import Issue, IssueActivity, Project, ProjectMember, State, User, WorkspaceMember
from plane.utils.conjo_state_timeline import build_state_timeline

H = datetime.timedelta(hours=1)


@pytest.fixture
def project(db, workspace, create_user):
    project = Project.objects.create(name="Fretes", identifier="FRT", workspace=workspace, created_by=create_user)
    ProjectMember.objects.create(project=project, member=create_user, role=20, is_active=True)
    return project


@pytest.fixture
def states(project, workspace):
    def make(name, group, **extra):
        return State.objects.create(name=name, group=group, project=project, workspace=workspace, **extra)

    return {
        "todo": make("A fazer", "unstarted", default=True, color="#111111"),
        "doing": make("Em andamento", "started", color="#222222"),
        "review": make("Em revisão", "started", color="#333333"),
        "done": make("Concluída", "completed", color="#444444"),
    }


def move(issue, old, new, at):
    activity = IssueActivity.objects.create(
        issue=issue,
        project=issue.project,
        workspace=issue.workspace,
        verb="updated",
        field="state",
        old_value=old.name if old else None,
        new_value=new.name,
        old_identifier=old.id if old else None,
        new_identifier=new.id,
    )
    IssueActivity.objects.filter(pk=activity.pk).update(created_at=at)


def card_created_at(project, state, at):
    issue = Issue.objects.create(name="Cotação", project=project, state=state)
    Issue.objects.filter(pk=issue.pk).update(created_at=at)
    issue.refresh_from_db()
    return issue


@pytest.mark.contract
class TestStateChangedAt:
    def test_set_on_create_and_on_every_move(self, project, states):
        issue = Issue.objects.create(name="Cotação", project=project, state=states["todo"])
        assert issue.state_changed_at is not None
        entered = issue.state_changed_at

        issue.name = "Cotação urgente"
        issue.save()
        issue.refresh_from_db()
        assert issue.state_changed_at == entered  # no move, no reset

        issue.state = states["doing"]
        issue.save()
        issue.refresh_from_db()
        assert issue.state_changed_at > entered
        assert issue.completed_at is None

        issue.state = states["done"]
        issue.save(update_fields=["state"])
        issue.refresh_from_db()
        assert issue.completed_at is not None
        assert issue.state_changed_at == issue.completed_at


@pytest.mark.contract
class TestStateTimeline:
    def test_time_per_column_until_done(self, project, states):
        start = timezone.now() - 100 * H
        issue = card_created_at(project, states["todo"], start)
        move(issue, states["todo"], states["doing"], start + 10 * H)
        move(issue, states["doing"], states["review"], start + 40 * H)
        move(issue, states["review"], states["doing"], start + 45 * H)
        move(issue, states["doing"], states["done"], start + 60 * H)
        Issue.objects.filter(pk=issue.pk).update(state=states["done"], state_changed_at=start + 60 * H)
        issue.refresh_from_db()

        timeline = build_state_timeline(issue)

        assert [s["name"] for s in timeline["segments"]] == [
            "A fazer",
            "Em andamento",
            "Em revisão",
            "Em andamento",
            "Concluída",
        ]
        assert [s["seconds"] for s in timeline["segments"]] == [36000, 108000, 18000, 54000, None]
        totals = {t["name"]: t["seconds"] for t in timeline["totals"]}
        assert totals == {"A fazer": 36000, "Em andamento": 162000, "Em revisão": 18000}
        assert timeline["is_done"] is True
        assert timeline["lead_seconds"] == 60 * 3600  # the clock stops at done
        assert timeline["segments"][-1]["color"] == "#444444"

    def test_open_card_keeps_counting_in_current_column(self, project, states):
        start = timezone.now() - 5 * H
        issue = card_created_at(project, states["todo"], start)
        move(issue, states["todo"], states["doing"], start + 2 * H)
        Issue.objects.filter(pk=issue.pk).update(state=states["doing"], state_changed_at=start + 2 * H)
        issue.refresh_from_db()

        timeline = build_state_timeline(issue, now=start + 5 * H)

        assert timeline["is_done"] is False
        assert timeline["current"]["name"] == "Em andamento"
        assert [s["seconds"] for s in timeline["segments"]] == [2 * 3600, 3 * 3600]
        assert timeline["segments"][-1]["ended_at"] is None
        assert timeline["lead_seconds"] == 5 * 3600

    def test_card_that_never_moved(self, project, states):
        start = timezone.now() - 3 * H
        issue = card_created_at(project, states["todo"], start)
        timeline = build_state_timeline(issue, now=start + 3 * H)
        assert [(s["name"], s["seconds"]) for s in timeline["segments"]] == [("A fazer", 3 * 3600)]

    def test_history_lagging_behind_the_card(self, project, states):
        # the activity is written by a background task: the card already moved, its history not yet
        start = timezone.now() - 4 * H
        issue = card_created_at(project, states["todo"], start)
        move(issue, states["todo"], states["doing"], start + H)
        Issue.objects.filter(pk=issue.pk).update(state=states["review"], state_changed_at=start + 3 * H)
        issue.refresh_from_db()

        timeline = build_state_timeline(issue, now=start + 4 * H)
        assert [(s["name"], s["seconds"]) for s in timeline["segments"]] == [
            ("A fazer", 3600),
            ("Em andamento", 2 * 3600),
            ("Em revisão", 3600),
        ]

    def test_removed_state_keeps_its_name(self, project, states):
        start = timezone.now() - 4 * H
        old = State.objects.create(name="Waiting", group="started", project=project, workspace=project.workspace)
        issue = card_created_at(project, old, start)
        move(issue, old, states["doing"], start + H)
        Issue.objects.filter(pk=issue.pk).update(state=states["doing"], state_changed_at=start + H)
        old.delete()
        issue.refresh_from_db()

        timeline = build_state_timeline(issue, now=start + 4 * H)
        assert timeline["segments"][0]["name"] == "Waiting"


@pytest.mark.contract
class TestStateTimelineEndpoint:
    def test_member_reads_the_timeline(self, project, states, workspace, session_client):
        issue = Issue.objects.create(name="Cotação", project=project, state=states["todo"])
        url = f"/api/workspaces/{workspace.slug}/projects/{project.id}/issues/{issue.id}/state-timeline/"
        response = session_client.get(url)
        assert response.status_code == 200
        assert response.json()["current"]["name"] == "A fazer"

    def test_outsider_and_foreign_card_are_refused(self, project, states, workspace, session_client):
        issue = Issue.objects.create(name="Cotação", project=project, state=states["todo"])
        outsider = User.objects.create(email="fora@example.com", username="fora")
        client = APIClient()
        client.force_authenticate(outsider)
        url = f"/api/workspaces/{workspace.slug}/projects/{project.id}/issues/{issue.id}/state-timeline/"
        assert client.get(url).status_code in (403, 404)

        other = Project.objects.create(name="Outro", identifier="OUT", workspace=workspace)
        foreign = Issue.objects.create(name="x", project=other)
        url = f"/api/workspaces/{workspace.slug}/projects/{project.id}/issues/{foreign.id}/state-timeline/"
        assert session_client.get(url).status_code == 404

    def test_guest_sees_only_own_cards(self, project, states, workspace):
        guest = User.objects.create(email="convidado@example.com", username="convidado")
        WorkspaceMember.objects.create(workspace=workspace, member=guest, role=5)
        ProjectMember.objects.create(project=project, member=guest, role=5, is_active=True)
        issue = Issue.objects.create(name="Cotação", project=project, state=states["todo"])
        client = APIClient()
        client.force_authenticate(guest)
        url = f"/api/workspaces/{workspace.slug}/projects/{project.id}/issues/{issue.id}/state-timeline/"
        assert client.get(url).status_code == 403


@pytest.mark.contract
class TestStatesInPortuguese:
    def test_migration_renames_english_columns(self, project, workspace):
        names = ["Backlog", "Todo", "In Progress", "Done", "Cancelled", "Waiting"]
        for name in names:
            State.objects.create(name=name, group="started", project=project, workspace=workspace)
        other = Project.objects.create(name="Outro", identifier="OUT", workspace=workspace)
        State.objects.create(name="Done", group="completed", project=other, workspace=workspace)
        State.objects.create(name="Concluída", group="completed", project=other, workspace=workspace)

        migration = importlib.import_module("plane.db.migrations.0136_conjo_states_ptbr_state_changed_at")
        migration.rename_states(django_apps, None)

        assert sorted(State.objects.filter(project=project).values_list("name", flat=True)) == sorted(
            ["Backlog", "A fazer", "Em andamento", "Concluída", "Cancelada", "Aguardando"]
        )
        assert State.objects.get(project=project, name="Em andamento").slug == "em-andamento"
        # the Portuguese name was taken in that project: the old column stays as it was
        assert sorted(State.objects.filter(project=other).values_list("name", flat=True)) == ["Concluída", "Done"]
