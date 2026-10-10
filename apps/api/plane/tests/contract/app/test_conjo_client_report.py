# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Client activity report (MAN-258): access, scope, exclusions, totals and period."""

# Fixtures are shared with test_conjo_billing (pytest injects them by name).
# ruff: noqa: F401, F811

import datetime
from decimal import Decimal
from unittest import mock

import pytest
from rest_framework.test import APIClient

from plane.db.models import (
    Client,
    ClientProject,
    HourLedgerEntry,
    IntakePortalBudget,
    Issue,
    IssueClient,
    IssueLabel,
    IssueWorkKind,
    IssueWorkLog,
    Label,
    Project,
    ProjectMember,
    State,
    User,
    Workspace,
    WorkspaceMember,
)
from plane.utils import conjo_billing as billing
from plane.utils.conjo_client_report import parse_period, report_number

from .test_conjo_billing import client_, make_contract, make_issue, project

D = Decimal
SEPT = {"from": "2026-09-01", "to": "2026-09-30"}


@pytest.fixture(autouse=True)
def no_side_tasks():
    with mock.patch("plane.bgtasks.conjo_billing_task.notify_low_balance.delay"):
        yield


def url(workspace, client):
    return f"/api/workspaces/{workspace.slug}/clients/{client.id}/report/"


def log(issue, minutes, day, text="Ajuste"):
    return IssueWorkLog.objects.create(
        issue=issue,
        project_id=issue.project_id,
        member=User.objects.get(email="test@plane.so"),
        minutes=minutes,
        logged_on=day,
        description=text,
    )


def kind(issue, value):
    IssueWorkKind.objects.create(issue=issue, project_id=issue.project_id, kind=value)
    return issue


def api_for(workspace, email, role, project=None, project_role=None):
    user = User.objects.create(email=email, username=email.split("@")[0], first_name=email.split("@")[0])
    if role is not None:
        WorkspaceMember.objects.create(workspace=workspace, member=user, role=role)
    if project is not None:
        ProjectMember.objects.create(project=project, member=user, role=project_role, is_active=True)
    api = APIClient()
    api.force_authenticate(user=user)
    return api


@pytest.fixture
def report_data(workspace, project, client_):
    """Sept/2026: evolution 3h + maintenance 1h30 reported; internal, unclassified and other months out."""
    done = State.objects.create(name="Feito", group="completed", project=project, workspace=workspace)
    evo = kind(make_issue(project, "Lembrete pelo WhatsApp"), "evolution")
    man = kind(make_issue(project, "Agenda mais rápida"), "maintenance")
    Issue.objects.filter(pk=man.pk).update(state=done)
    internal = kind(make_issue(project, "Refatoração interna sigilosa"), "internal")
    loose = make_issue(project, "Item sem tipo")
    agenda = Label.objects.create(name="Agenda", project=project, workspace=workspace)
    IssueLabel.objects.create(issue=man, label=agenda, project=project)
    log(evo, 120, datetime.date(2026, 9, 4), "Modelo de mensagem aprovado")
    log(evo, 60, datetime.date(2026, 9, 6), "Confirmação pela resposta")
    log(man, 90, datetime.date(2026, 9, 2), "Consultas agrupadas")
    log(internal, 300, datetime.date(2026, 9, 10), "Segredo interno")
    log(loose, 45, datetime.date(2026, 9, 11), "Sem tipo")
    log(evo, 600, datetime.date(2026, 10, 1), "Fora do período")
    log(man, 600, datetime.date(2026, 8, 31), "Fora do período")
    return {"evo": evo, "man": man, "internal": internal, "loose": loose}


@pytest.mark.contract
class TestReportAccess:
    def test_admin_gets_the_report(self, session_client, workspace, client_, report_data):
        response = session_client.get(url(workspace, client_), SEPT)
        assert response.status_code == 200
        assert response.json()["client"]["name"] == "Cliente Exemplo"

    def test_workspace_guest_is_refused(self, workspace, project, client_, report_data):
        api = api_for(workspace, "convidado@x.com", 5, project, 5)
        assert api.get(url(workspace, client_), SEPT).status_code == 403

    def test_outsider_is_refused(self, workspace, client_, report_data):
        api = api_for(workspace, "fora@x.com", None)
        assert api.get(url(workspace, client_), SEPT).status_code == 403

    def test_client_of_another_workspace_is_not_found(self, session_client, workspace, create_user):
        other = Workspace.objects.create(name="Outro", owner=create_user, slug="outro-ws")
        foreign = Client.objects.create(workspace=other, name="Cliente de fora")
        # Same user, admin in both workspaces: the client must still be addressed under its own workspace.
        WorkspaceMember.objects.create(workspace=other, member=create_user, role=20)
        assert session_client.get(url(workspace, foreign), SEPT).status_code == 404

    def test_member_without_the_project_sees_nothing_of_it(self, workspace, project, client_, report_data):
        api = api_for(workspace, "membro@x.com", 15)
        response = api.get(url(workspace, client_), SEPT)
        assert response.status_code == 200
        data = response.json()
        assert data["rows"] == [] and data["highlights"] == []
        assert data["totals"]["minutes"] == 0
        assert [w["type"] for w in data["warnings"]] == ["partial"]
        assert "Lembrete" not in str(data)

    def test_member_of_the_project_sees_it(self, workspace, project, client_, report_data):
        api = api_for(workspace, "membro2@x.com", 15, project, 15)
        data = api.get(url(workspace, client_), SEPT).json()
        assert data["totals"]["minutes"] == 270
        assert not [w for w in data["warnings"] if w["type"] == "partial"]


@pytest.mark.contract
class TestReportContent:
    def test_totals_exclude_internal_unclassified_and_other_months(
        self, session_client, workspace, client_, report_data
    ):
        data = session_client.get(url(workspace, client_), SEPT).json()
        assert data["totals"]["evolution_minutes"] == 180
        assert data["totals"]["maintenance_minutes"] == 90
        assert data["totals"]["minutes"] == 270
        assert data["totals"]["hours"] == "4.50"
        assert data["totals"]["items"] == 2 and data["totals"]["done_items"] == 1
        assert [r["date"] for r in data["rows"]] == ["2026-09-02", "2026-09-04", "2026-09-06"]
        text = str(data["rows"]) + str(data["highlights"]) + str(data["by_system"])
        assert "sigilosa" not in text and "Segredo" not in text and "Fora do período" not in text
        assert "Sem tipo" not in text

    def test_unclassified_items_are_only_a_warning(self, session_client, workspace, client_, report_data):
        data = session_client.get(url(workspace, client_), SEPT).json()
        warning = next(w for w in data["warnings"] if w["type"] == "unclassified")
        assert [i["title"] for i in warning["items"]] == ["Item sem tipo"]
        assert warning["items"][0]["hours"] == "0.75"

    def test_rows_do_not_expose_the_member(self, session_client, workspace, client_, report_data, create_user):
        data = session_client.get(url(workspace, client_), SEPT).json()
        assert create_user.email not in str(data)
        assert set(data["rows"][0]) == {"id", "date", "key", "kind", "title", "description", "minutes", "hours"}

    def test_systems_highlights_and_next_steps(self, session_client, workspace, client_, report_data):
        data = session_client.get(url(workspace, client_), SEPT).json()
        systems = {s["name"]: s for s in data["by_system"]}
        assert systems["Agenda"]["maintenance_minutes"] == 90
        assert systems["Geral"]["evolution_minutes"] == 180
        assert [h["title"] for h in data["highlights"]] == ["Lembrete pelo WhatsApp", "Agenda mais rápida"]
        assert data["highlights"][0]["summary"] == "Modelo de mensagem aprovado. Confirmação pela resposta."
        assert [n["title"] for n in data["next_steps"]] == ["Lembrete pelo WhatsApp"]

    def test_items_of_another_client_on_the_same_board_stay_out(
        self, session_client, workspace, project, client_, report_data
    ):
        other = Client.objects.create(workspace=workspace, name="Outro cliente")
        foreign = kind(make_issue(project, "Chamado do outro cliente"), "evolution")
        IssueClient.objects.create(issue=foreign, client=other, project=project)
        log(foreign, 240, datetime.date(2026, 9, 15))
        data = session_client.get(url(workspace, client_), SEPT).json()
        assert "outro cliente" not in str(data).lower()
        assert data["totals"]["minutes"] == 270
        other_data = session_client.get(url(workspace, other), SEPT).json()
        assert other_data["totals"]["minutes"] == 240

    def test_items_without_client_stay_out(self, session_client, workspace, create_user, client_, report_data):
        loose_project = Project.objects.create(
            name="Avulso", identifier="AVU", workspace=workspace, created_by=create_user
        )
        ProjectMember.objects.create(project=loose_project, member=create_user, role=20, is_active=True)
        issue = kind(make_issue(loose_project, "Sem cliente"), "evolution")
        log(issue, 120, datetime.date(2026, 9, 3))
        data = session_client.get(url(workspace, client_), SEPT).json()
        assert data["totals"]["minutes"] == 270 and "Sem cliente" not in str(data)

    def test_package_numbers_come_from_the_statement(self, session_client, workspace, client_, report_data):
        contract = make_contract(client_, starts_on=datetime.date(2026, 7, 1))
        with mock.patch("plane.utils.conjo_billing.today", return_value=datetime.date(2026, 10, 5)):
            billing.refresh_contract(contract, on=datetime.date(2026, 9, 1))
            HourLedgerEntry.objects.create(
                workspace_id=contract.workspace_id,
                contract=contract,
                kind="debit",
                hours=D("-5"),
                occurred_on=datetime.date(2026, 8, 10),
            )
            HourLedgerEntry.objects.create(
                workspace_id=contract.workspace_id,
                contract=contract,
                kind="debit",
                hours=D("-8"),
                occurred_on=datetime.date(2026, 9, 10),
            )
            data = session_client.get(url(workspace, client_), SEPT).json()
        pkg = data["package"]
        assert data["contract"]["name"] == "Pacote 20h"
        # 3 months of accumulation: July's credit expires on 30/09 (written off that day), August and
        # September (20h each) are still valid after the period.
        assert pkg["contracted"] == "40.00"
        assert pkg["used_in_period"] == "8.00"
        assert pkg["balance"] == "27.00"
        assert pkg["used_before"] == "5.00"
        assert pkg["valid_until"] == "2026-11-30" and pkg["next_expiry"] == "2026-10-31"

    def test_without_contract_the_package_is_empty(self, session_client, workspace, client_, report_data):
        data = session_client.get(url(workspace, client_), SEPT).json()
        assert data["package"] is None and data["contract"] is None
        assert data["owner"] == "Conjo SA"


@pytest.mark.contract
class TestReportPeriod:
    def test_default_is_the_previous_month(self):
        start, end = parse_period({}, today=datetime.date(2026, 10, 10))
        assert (start, end) == (datetime.date(2026, 9, 1), datetime.date(2026, 9, 30))
        start, end = parse_period({}, today=datetime.date(2027, 1, 3))
        assert (start, end) == (datetime.date(2026, 12, 1), datetime.date(2026, 12, 31))

    @pytest.mark.parametrize(
        "params",
        [{"from": "2026-09-30", "to": "2026-09-01"}, {"from": "abc"}, {"from": "2025-01-01", "to": "2026-09-30"}],
    )
    def test_invalid_period_is_refused(self, session_client, workspace, client_, params):
        assert session_client.get(url(workspace, client_), params).status_code == 400

    def test_number_is_deterministic(self, client_):
        month = report_number(client_, datetime.date(2026, 9, 1), datetime.date(2026, 9, 30))
        assert month == report_number(client_, datetime.date(2026, 9, 1), datetime.date(2026, 9, 30))
        assert month.startswith("RA-2026-09-")
        custom = report_number(client_, datetime.date(2026, 9, 1), datetime.date(2026, 9, 15))
        assert custom.startswith("RA-20260901-20260915-")

    def test_single_day_period(self, session_client, workspace, client_, report_data):
        data = session_client.get(url(workspace, client_), {"from": "2026-09-04", "to": "2026-09-04"}).json()
        assert data["totals"]["minutes"] == 120
