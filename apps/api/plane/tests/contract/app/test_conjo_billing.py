# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Hour packages, time spent, clients and the client timeline."""

import datetime
from decimal import Decimal
from unittest import mock

import pytest
from django.utils import timezone
from rest_framework import status

from plane.bgtasks.conjo_billing_task import debit_approved_estimate
from plane.db.models import (
    Client,
    ClientContact,
    ClientContract,
    ClientProject,
    HourLedgerEntry,
    Intake,
    IntakeIssue,
    IntakePortalBudget,
    Issue,
    IssueWorkKind,
    IssueWorkLog,
    Project,
    ProjectMember,
    State,
)
from plane.utils import conjo_billing as billing
from plane.utils.conjo_github import parse_smart_commands

D = Decimal


@pytest.fixture(autouse=True)
def no_side_tasks():
    with mock.patch("plane.bgtasks.conjo_billing_task.notify_low_balance.delay"):
        yield


@pytest.fixture
def project(db, workspace, create_user):
    project = Project.objects.create(name="Fretes", identifier="EXM", workspace=workspace, created_by=create_user)
    ProjectMember.objects.create(project=project, member=create_user, role=20, is_active=True)
    State.objects.create(name="A fazer", group="unstarted", project=project, workspace=workspace, default=True)
    return project


@pytest.fixture
def client_(workspace, project):
    client = Client.objects.create(workspace=workspace, name="Cliente Exemplo")
    ClientProject.objects.create(workspace=workspace, client=client, project=project)
    ClientContact.objects.create(
        workspace=workspace, client=client, name="Maria", email="maria@cliente.com.br", can_approve=True
    )
    return client


def make_contract(client, starts_on=datetime.date(2026, 7, 1), hours="20", months=3):
    contract = ClientContract.objects.create(
        workspace_id=client.workspace_id,
        client=client,
        name="Pacote 20h",
        hours_per_month=D(hours),
        accumulation_months=months,
        starts_on=starts_on,
    )
    # Pretend it was registered at the start, so past months are credited.
    ClientContract.objects.filter(pk=contract.pk).update(
        created_at=timezone.make_aware(datetime.datetime.combine(starts_on, datetime.time(9)))
    )
    contract.refresh_from_db()
    return contract


def make_issue(project, name="Relatório de fretes"):
    return Issue.objects.create(name=name, project=project)


@pytest.mark.unit
class TestDurations:
    @pytest.mark.parametrize(
        "text,minutes",
        [("1h30", 90), ("1h 30m", 90), ("90m", 90), ("45min", 45), ("1,5h", 90), ("2h", 120), ("2", 120), ("90", 90)],
    )
    def test_parse(self, text, minutes):
        assert billing.parse_duration(text) == minutes

    @pytest.mark.parametrize("text", ["", "abc", "0", None])
    def test_invalid(self, text):
        assert billing.parse_duration(text) is None

    def test_expiry(self):
        assert billing.lot_expiry(datetime.date(2026, 10, 1), 3) == datetime.date(2026, 12, 31)
        assert billing.lot_expiry(datetime.date(2026, 11, 1), 12) == datetime.date(2027, 10, 31)
        assert billing.lot_expiry(datetime.date(2026, 10, 1), 1) == datetime.date(2026, 10, 31)

    def test_time_smart_command(self):
        commands = parse_smart_commands("EXM-45 #time 1h30 ajustes #comment feito")
        assert commands[("EXM", 45)]["times"] == ["1h30"]


@pytest.mark.contract
class TestLedger:
    def test_credits_expire_after_the_window_and_debits_take_the_oldest_lot(self, client_):
        contract = make_contract(client_)
        billing.ensure_monthly_credits(contract, on=datetime.date(2026, 9, 15))
        assert billing.balance(contract, on=datetime.date(2026, 9, 15)) == D("60")  # jul, aug, sep

        issue = make_issue(client_.client_projects.first().project)
        debit = billing.debit_for_estimate(issue, D("8"), "maria@cliente.com.br", on=datetime.date(2026, 9, 15))
        july = HourLedgerEntry.objects.get(contract=contract, kind="credit", period=datetime.date(2026, 7, 1))
        assert debit.hours == D("-8") and july.remaining == D("12")
        assert debit.allocations[0]["lot"] == str(july.id)

        # October: July's lot (valid until Sep 30) expires; October is credited.
        billing.refresh_contract(contract, on=datetime.date(2026, 10, 1))
        expiration = HourLedgerEntry.objects.get(contract=contract, kind="expiration")
        assert expiration.hours == D("-12")
        assert billing.balance(contract, on=datetime.date(2026, 10, 1)) == D("60")  # aug, sep, oct

    def test_excess_beyond_balance_is_recorded_without_touching_the_balance(self, client_):
        contract = make_contract(client_, starts_on=datetime.date(2026, 10, 1))
        billing.ensure_monthly_credits(contract, on=datetime.date(2026, 10, 2))
        issue = make_issue(client_.client_projects.first().project)
        billing.debit_for_estimate(issue, D("26"), on=datetime.date(2026, 10, 2))
        excess = HourLedgerEntry.objects.get(contract=contract, kind="excess")
        assert excess.hours == D("6")
        assert billing.balance(contract, on=datetime.date(2026, 10, 2)) == D("0")
        rows = billing.statement(contract)
        assert rows[0][1] == D("0")  # running balance ignores the excess

    def test_debit_is_idempotent_and_skips_maintenance(self, client_):
        contract = make_contract(client_, starts_on=datetime.date(2026, 10, 1))
        project = client_.client_projects.first().project
        issue = make_issue(project)
        billing.debit_for_estimate(issue, D("5"), on=datetime.date(2026, 10, 2))
        assert billing.debit_for_estimate(issue, D("5"), on=datetime.date(2026, 10, 2)) is None
        bug = make_issue(project, "Erro no CSV")
        IssueWorkKind.objects.create(issue=bug, project=project, kind=IssueWorkKind.MAINTENANCE)
        assert billing.debit_for_estimate(bug, D("3"), on=datetime.date(2026, 10, 2)) is None
        assert billing.balance(contract, on=datetime.date(2026, 10, 2)) == D("15")

    def test_reversal_returns_hours_to_their_lot(self, client_):
        contract = make_contract(client_, starts_on=datetime.date(2026, 10, 1))
        issue = make_issue(client_.client_projects.first().project)
        debit = billing.debit_for_estimate(issue, D("8"), on=datetime.date(2026, 10, 2))
        billing.reverse_debit(debit, on=datetime.date(2026, 10, 3))
        assert billing.balance(contract, on=datetime.date(2026, 10, 3)) == D("20")
        assert billing.reverse_debit(debit) is None

    def test_adjustments(self, client_):
        contract = make_contract(client_, starts_on=datetime.date(2026, 10, 1))
        billing.ensure_monthly_credits(contract, on=datetime.date(2026, 10, 2))
        billing.adjust(contract, D("10"), "saldo inicial", on=datetime.date(2026, 10, 2))
        billing.adjust(contract, D("-4"), "correção", on=datetime.date(2026, 10, 2))
        assert billing.balance(contract, on=datetime.date(2026, 10, 2)) == D("26")


@pytest.mark.contract
class TestApprovalAndKind:
    def test_portal_approval_debits_and_kind_switch_reverses(self, session_client, workspace, client_):
        contract = make_contract(client_, starts_on=billing.month_start(billing.today()))
        project = client_.client_projects.first().project
        issue = make_issue(project)
        IntakePortalBudget.objects.create(
            issue=issue, project=project, estimated_hours=D("8"), status="APPROVED", approved_by_email="maria@x.com"
        )
        debit_approved_estimate(issue.id, D("8"), "maria@x.com")
        assert billing.balance(contract) == D("12")
        assert IssueWorkKind.objects.get(issue=issue).kind == IssueWorkKind.EVOLUTION

        url = f"/api/workspaces/{workspace.slug}/projects/{project.id}/issues/{issue.id}/work-kind/"
        assert session_client.put(url, {"kind": "maintenance"}, format="json").status_code == 200
        assert billing.balance(contract) == D("20")
        assert session_client.put(url, {"kind": "evolution"}, format="json").status_code == 200
        assert billing.balance(contract) == D("12")


@pytest.mark.contract
class TestTimeEndpoints:
    def test_log_edit_and_delete_time(self, session_client, workspace, project, create_user):
        issue = make_issue(project)
        url = f"/api/workspaces/{workspace.slug}/projects/{project.id}/issues/{issue.id}/time/"
        response = session_client.post(url, {"duration": "1h30", "description": "filtro"}, format="json")
        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["total_minutes"] == 90 and data["entries"][0]["member"]["id"] == str(create_user.id)

        entry_id = data["entries"][0]["id"]
        data = session_client.patch(f"{url}{entry_id}/", {"duration": "2h"}, format="json").json()
        assert data["total_minutes"] == 120
        assert session_client.post(url, {"duration": "xyz"}, format="json").status_code == 400
        data = session_client.delete(f"{url}{entry_id}/").json()
        assert data["total_minutes"] == 0 and not IssueWorkLog.objects.exists()

    def test_manual_time_requires_description(self, session_client, workspace, project):
        issue = make_issue(project)
        url = f"/api/workspaces/{workspace.slug}/projects/{project.id}/issues/{issue.id}/time/"
        for payload in (
            {"duration": "1h"},
            {"duration": "1h", "description": ""},
            {"duration": "1h", "description": "  "},
        ):
            response = session_client.post(url, payload, format="json")
            assert response.status_code == status.HTTP_400_BAD_REQUEST
            assert response.json()["error"] == "Descreva o que foi feito."
        assert not IssueWorkLog.objects.filter(issue=issue).exists()

        response = session_client.post(url, {"duration": "1h", "description": " ajuste no filtro "}, format="json")
        assert response.status_code == status.HTTP_201_CREATED
        entry_id = response.json()["entries"][0]["id"]
        assert IssueWorkLog.objects.get(pk=entry_id).description == "ajuste no filtro"

        # Editing cannot clear the description.
        response = session_client.patch(f"{url}{entry_id}/", {"description": "   "}, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["error"] == "Descreva o que foi feito."
        assert IssueWorkLog.objects.get(pk=entry_id).description == "ajuste no filtro"

    def test_old_entry_without_description_saves_only_with_one(self, session_client, workspace, project, create_user):
        issue = make_issue(project)
        url = f"/api/workspaces/{workspace.slug}/projects/{project.id}/issues/{issue.id}/time/"
        old = IssueWorkLog.objects.create(
            issue=issue, project=project, member=create_user, minutes=60, logged_on=billing.today(), description=""
        )
        # Still listed (valid), but an edit that keeps it empty is refused.
        assert session_client.get(url).json()["total_minutes"] == 60
        response = session_client.patch(f"{url}{old.id}/", {"duration": "2h"}, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        old.refresh_from_db()
        assert old.minutes == 60
        response = session_client.patch(f"{url}{old.id}/", {"duration": "2h", "description": "revisão"}, format="json")
        assert response.status_code == status.HTTP_200_OK
        old.refresh_from_db()
        assert old.minutes == 120 and old.description == "revisão"

    def test_commit_time_without_description_still_accepted(self, session_client, workspace, project, create_user):
        from plane.bgtasks.conjo_github_task import log_commit_time

        issue = make_issue(project)
        log_commit_time(issue, create_user, "1h", "abc1234", "x/y")
        entry = IssueWorkLog.objects.get(issue=issue, source=IssueWorkLog.SOURCE_COMMIT)
        assert entry.minutes == 60
        # Automatic entries keep their old rules: an edit may leave the description empty.
        url = f"/api/workspaces/{workspace.slug}/projects/{project.id}/issues/{issue.id}/time/{entry.id}/"
        response = session_client.patch(url, {"description": ""}, format="json")
        assert response.status_code == status.HTTP_200_OK
        entry.refresh_from_db()
        assert entry.description == ""
        chat = IssueWorkLog.objects.create(
            issue=issue,
            project=project,
            member=create_user,
            minutes=30,
            logged_on=billing.today(),
            source=IssueWorkLog.SOURCE_CHAT,
        )
        url = f"/api/workspaces/{workspace.slug}/projects/{project.id}/issues/{issue.id}/time/{chat.id}/"
        assert session_client.patch(url, {"duration": "45min"}, format="json").status_code == status.HTTP_200_OK


@pytest.mark.contract
class TestClientEndpoints:
    def test_client_contract_and_ledger_flow(self, session_client, workspace, project):
        base = f"/api/workspaces/{workspace.slug}/clients/"
        client_id = session_client.post(base, {"name": "Cliente Novo"}, format="json").json()["id"]
        detail = f"{base}{client_id}/"
        assert (
            session_client.put(f"{detail}projects/", {"project_ids": [str(project.id)]}, format="json").status_code
            == 200
        )
        response = session_client.post(
            f"{detail}contracts/",
            {
                "name": "Pacote 20h",
                "hours_per_month": "20",
                "accumulation_months": 3,
                "starts_on": billing.today().isoformat(),
                "opening_balance": "5",
            },
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED
        ledger = session_client.get(f"{detail}ledger/").json()
        assert ledger["package"]["available"] in ("25.00", "25")
        assert {e["kind"] for e in ledger["entries"]} == {"credit", "adjustment"}

        assert session_client.post(f"{detail}ledger/adjust/", {"hours": "3"}, format="json").status_code == 400
        assert (
            session_client.post(f"{detail}ledger/adjust/", {"hours": "-3", "note": "acerto"}, format="json").status_code
            == 201
        )
        assert session_client.get(f"{detail}").json()["package"]["available"] in ("22.00", "22")
        csv_response = session_client.get(f"{detail}ledger/export/")
        assert csv_response.status_code == 200 and "movimento" in csv_response.content.decode("utf-8")

    def test_project_belongs_to_one_client(self, session_client, workspace, project, client_):
        base = f"/api/workspaces/{workspace.slug}/clients/"
        other = session_client.post(base, {"name": "Outro"}, format="json").json()["id"]
        response = session_client.put(f"{base}{other}/projects/", {"project_ids": [str(project.id)]}, format="json")
        assert response.status_code == 400


@pytest.mark.contract
class TestTimeline:
    def test_timeline_merges_sources(self, session_client, workspace, client_, project):
        make_contract(client_, starts_on=billing.month_start(billing.today()))
        issue = make_issue(project)
        intake = Intake.objects.create(name="Entrada", project=project)
        IntakeIssue.objects.create(
            intake=intake,
            project=project,
            issue=issue,
            source="PORTAL",
            source_email="maria@cliente.com.br",
            extra={"requester_name": "Maria"},
        )
        base = f"/api/workspaces/{workspace.slug}/clients/{client_.id}/timeline/"
        session_client.post(f"{base}notes/", {"kind": "meeting", "body": "Roadmap do trimestre"}, format="json")
        events = session_client.get(base).json()["events"]
        types = {event["type"] for event in events}
        assert {"note", "ledger", "request"} <= types
        only_contacts = session_client.get(f"{base}?types=contacts").json()["events"]
        assert {event["type"] for event in only_contacts} == {"note"}


@pytest.mark.contract
class TestPortalPackage:
    def test_package_only_for_registered_contacts(self, client_, project):
        make_contract(client_, starts_on=billing.month_start(billing.today()))
        package = billing.portal_package(project.id, "MARIA@cliente.com.br")
        assert package["available"] in ("20.00", "20") and package["client_name"] == "Cliente Exemplo"
        assert billing.portal_package(project.id, "estranho@x.com") is None
