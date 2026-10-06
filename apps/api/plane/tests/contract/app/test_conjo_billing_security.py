# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Hour packages: permissions, ledger integrity under repeated calls and hostile input."""

# Fixtures are shared with test_conjo_billing (pytest injects them by name).
# ruff: noqa: F401, F811

import datetime
from decimal import Decimal
from unittest import mock

import pytest
from django.db import IntegrityError, transaction
from rest_framework.test import APIClient

from plane.db.models import (
    ClientContact,
    ClientContract,
    ClientProject,
    HourLedgerEntry,
    Intake,
    IntakeIssue,
    IntakePortal,
    IntakePortalBudget,
    Issue,
    IssueWorkKind,
    IssueWorkLog,
    Project,
    ProjectMember,
    User,
    WorkspaceMember,
)
from plane.db.models.intake import SourceType
from plane.space.views.portal_auth import create_session
from plane.utils import conjo_billing as billing
from plane.utils.conjo_github import parse_smart_commands

from .test_conjo_billing import client_, make_contract, make_issue, project

D = Decimal


@pytest.fixture(autouse=True)
def no_side_tasks():
    with mock.patch("plane.bgtasks.conjo_billing_task.notify_low_balance.delay"):
        yield


@pytest.fixture
def member_client(workspace, project):
    user = User.objects.create(email="membro@conjo.local", username="membro", first_name="Membro")
    WorkspaceMember.objects.create(workspace=workspace, member=user, role=15)
    ProjectMember.objects.create(project=project, member=user, role=15, is_active=True)
    api = APIClient()
    api.force_authenticate(user=user)
    api.user = user
    return api


def approved_issue(project, hours="8"):
    issue = make_issue(project)
    IntakePortalBudget.objects.create(
        issue=issue, project=project, estimated_hours=D(hours), status="APPROVED", approved_by_email="maria@x.com"
    )
    return issue


@pytest.mark.contract
class TestLedgerIntegrity:
    def test_refreshing_twice_never_credits_a_month_twice(self, client_):
        contract = make_contract(client_)
        on = datetime.date(2026, 9, 15)
        billing.refresh_contract(contract, on=on)
        billing.refresh_contract(contract, on=on)
        assert HourLedgerEntry.objects.filter(contract=contract, kind="credit").count() == 3
        # The database refuses a second credit for the same month even if the lock were bypassed.
        with pytest.raises(IntegrityError), transaction.atomic():
            HourLedgerEntry.objects.create(
                workspace_id=contract.workspace_id,
                contract=contract,
                kind="credit",
                hours=D("20"),
                remaining=D("20"),
                period=datetime.date(2026, 7, 1),
                occurred_on=datetime.date(2026, 7, 1),
            )

    def test_debit_is_reversed_only_once(self, client_):
        contract = make_contract(client_, starts_on=billing.month_start(billing.today()))
        issue = approved_issue(client_.client_projects.first().project)
        debit = billing.debit_for_estimate(issue, D("8"), "maria@x.com")
        assert billing.reverse_debit(debit) is not None
        assert billing.reverse_debit(HourLedgerEntry.objects.get(pk=debit.pk)) is None
        assert billing.balance(contract) == D("20")

    def test_inactive_contract_earns_nothing(self, client_):
        contract = make_contract(client_)
        ClientContract.objects.filter(pk=contract.pk).update(is_active=False)
        contract.refresh_from_db()
        assert billing.ensure_monthly_credits(contract, on=datetime.date(2026, 9, 15)) == []
        assert not HourLedgerEntry.objects.filter(contract=contract).exists()

    def test_replacing_a_contract_moves_the_balance_and_does_not_credit_the_month_twice(
        self,
        session_client,
        workspace,
        client_,
    ):
        old = make_contract(client_, starts_on=billing.month_start(billing.today()))
        billing.refresh_contract(old)
        assert billing.balance(old) == D("20")
        url = f"/api/workspaces/{workspace.slug}/clients/{client_.id}/contracts/"
        response = session_client.post(
            url,
            {"name": "Pacote 40h", "hours_per_month": "40", "starts_on": billing.today().isoformat()},
            format="json",
        )
        assert response.status_code == 201
        new = ClientContract.objects.get(pk=response.json()["id"])
        old.refresh_from_db()
        assert not old.is_active and old.ends_on == billing.today()
        assert billing.balance(old) == D("0")
        # The 20h left move over; this month was already credited by the old package.
        assert billing.balance(new) == D("20")
        assert not HourLedgerEntry.objects.filter(contract=new, kind="credit").exists()

    def test_negative_adjustment_beyond_balance_is_refused(self, session_client, workspace, client_):
        make_contract(client_, starts_on=billing.month_start(billing.today()))
        url = f"/api/workspaces/{workspace.slug}/clients/{client_.id}/ledger/adjust/"
        response = session_client.post(url, {"hours": "-50", "note": "acerto"}, format="json")
        assert response.status_code == 400 and "Saldo insuficiente" in response.json()["error"]

    @pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity", "1e9", "abc", "0"])
    def test_hostile_hours_are_rejected(self, session_client, workspace, client_, value):
        make_contract(client_, starts_on=billing.month_start(billing.today()))
        base = f"/api/workspaces/{workspace.slug}/clients/{client_.id}"
        assert (
            session_client.post(f"{base}/ledger/adjust/", {"hours": value, "note": "x"}, format="json").status_code
            == 400
        )
        contract = {"name": "X", "hours_per_month": value, "starts_on": "2026-10-01"}
        assert session_client.post(f"{base}/contracts/", contract, format="json").status_code == 400

    def test_bad_project_list_and_export_period(self, session_client, workspace, client_):
        base = f"/api/workspaces/{workspace.slug}/clients/{client_.id}"
        assert session_client.put(f"{base}/projects/", {"project_ids": ["x"]}, format="json").status_code == 400
        assert session_client.put(f"{base}/projects/", {"project_ids": "abc"}, format="json").status_code == 400
        assert session_client.get(f"{base}/ledger/export/?from=lixo").status_code == 400


@pytest.mark.contract
class TestPermissions:
    def test_member_cannot_change_kind_of_an_item_with_a_debit(self, member_client, workspace, client_):
        contract = make_contract(client_, starts_on=billing.month_start(billing.today()))
        project = client_.client_projects.first().project
        issue = approved_issue(project)
        billing.debit_for_estimate(issue, D("8"), "maria@x.com")
        url = f"/api/workspaces/{workspace.slug}/projects/{project.id}/issues/{issue.id}/work-kind/"
        assert member_client.put(url, {"kind": "maintenance"}, format="json").status_code == 403
        assert billing.balance(contract) == D("12")
        # Items without an estimate are free for the team to classify.
        free = make_issue(project, "Sem orçamento")
        url = f"/api/workspaces/{workspace.slug}/projects/{project.id}/issues/{free.id}/work-kind/"
        assert member_client.put(url, {"kind": "maintenance"}, format="json").status_code == 200

    def test_timeline_and_ledger_hide_projects_the_member_is_not_in(
        self,
        member_client,
        workspace,
        client_,
        create_user,
    ):
        make_contract(client_, starts_on=billing.month_start(billing.today()))
        secret = Project.objects.create(name="Secreto", identifier="SEC", workspace=workspace, created_by=create_user)
        ClientProject.objects.create(workspace=workspace, client=client_, project=secret)
        issue = approved_issue(secret)
        billing.debit_for_estimate(issue, D("2"), "maria@x.com")
        base = f"/api/workspaces/{workspace.slug}/clients/{client_.id}"
        events = member_client.get(f"{base}/timeline/").json()["events"]
        assert all((event.get("issue") or {}).get("key", "").split("-")[0] != "SEC" for event in events)
        entries = member_client.get(f"{base}/ledger/").json()["entries"]
        debit = next(entry for entry in entries if entry["kind"] == "debit")
        assert debit["issue"] is None

    def test_export_neutralizes_formulas_and_marking_needs_a_post(self, session_client, workspace, client_):
        contract = make_contract(client_, starts_on=billing.month_start(billing.today()))
        project = client_.client_projects.first().project
        issue = approved_issue(project, hours="30")
        Issue.objects.filter(pk=issue.pk).update(name='=HYPERLINK("http://evil/","x")')
        issue.refresh_from_db()
        billing.debit_for_estimate(issue, D("30"), "maria@x.com")
        base = f"/api/workspaces/{workspace.slug}/clients/{client_.id}/ledger/export/"
        body = session_client.get(f"{base}?mark_exported=1").content.decode("utf-8-sig")
        assert "'=HYPERLINK" in body and ";=HYPERLINK" not in body
        excess = HourLedgerEntry.objects.get(contract=contract, kind="excess")
        assert excess.exported_at is None
        assert session_client.post(base, {}, format="json").json()["marked"] == 1


@pytest.mark.contract
class TestPortalApproval:
    @pytest.fixture
    def portal(self, workspace, project):
        intake = Intake.objects.create(name="Entrada", project=project, workspace=workspace)
        return IntakePortal.objects.create(project=project, workspace=workspace, intake=intake, is_enabled=True)

    def ticket(self, portal, email, hours="6"):
        issue = Issue.objects.create(name="Pedido", project=portal.project)
        IntakeIssue.objects.create(
            project=portal.project,
            workspace=portal.workspace,
            intake=portal.intake,
            issue=issue,
            source=SourceType.PORTAL,
            source_email=email,
        )
        IntakePortalBudget.objects.create(issue=issue, project=portal.project, estimated_hours=D(hours))
        return issue

    def approve(self, portal, issue, email):
        token = create_session(email, portal.workspace_id, portal.project_id)
        url = f"/api/public/intake-portal/{portal.anchor}/tickets/{issue.id}/budget/approve/"
        return APIClient().post(url, {}, format="json", HTTP_X_PORTAL_TOKEN=token)

    def test_only_contacts_that_can_approve_debit_the_package(self, portal, client_):
        contract = make_contract(client_, starts_on=billing.month_start(billing.today()))
        ClientContact.objects.create(
            workspace=client_.workspace, client=client_, name="João", email="joao@cliente.com.br", can_approve=False
        )
        joao_ticket = self.ticket(portal, "joao@cliente.com.br")
        response = self.approve(portal, joao_ticket, "joao@cliente.com.br")
        assert response.status_code == 403
        assert IntakePortalBudget.objects.get(issue=joao_ticket).status == "PENDING"

        maria_ticket = self.ticket(portal, "maria@cliente.com.br")
        assert self.approve(portal, maria_ticket, "maria@cliente.com.br").status_code == 200
        assert billing.balance(contract) == D("14")
        # A second click is refused and does not debit again.
        assert self.approve(portal, maria_ticket, "maria@cliente.com.br").status_code == 400
        assert billing.balance(contract) == D("14")

    def test_failed_debit_rolls_the_approval_back(self, portal, client_):
        make_contract(client_, starts_on=billing.month_start(billing.today()))
        issue = self.ticket(portal, "maria@cliente.com.br")
        with mock.patch("plane.utils.conjo_billing.consume", side_effect=RuntimeError("db down")):
            assert self.approve(portal, issue, "maria@cliente.com.br").status_code == 503
        assert IntakePortalBudget.objects.get(issue=issue).status == "PENDING"


@pytest.mark.unit
class TestCommitTime:
    def test_time_with_space_between_hours_and_minutes(self):
        assert parse_smart_commands("EXM-4 #time 1h 30m ajuste")[("EXM", 4)]["times"] == ["1h 30m"]

    def test_commit_from_non_member_logs_nothing(self, workspace, project, create_user):
        from plane.bgtasks.conjo_github_task import link_commits

        outsider = User.objects.create(email="fora@conjo.local", username="fora")
        WorkspaceMember.objects.create(workspace=workspace, member=outsider, role=15)
        issue = make_issue(project)
        commit = {
            "id": "a" * 40,
            "message": f"{project.identifier}-{issue.sequence_id} #time 8h",
            "url": "https://github.com/x/y/commit/aaa",
            "timestamp": "2026-10-01T10:00:00Z",
            "author": {"name": "Fora", "email": "fora@conjo.local", "username": "fora"},
        }
        link_commits(workspace, "x/y", "main", [commit])
        assert not IssueWorkLog.objects.filter(issue=issue).exists()
        commit = {**commit, "id": "b" * 40, "author": {"name": "T", "email": create_user.email, "username": "t"}}
        link_commits(workspace, "x/y", "main", [commit])
        log = IssueWorkLog.objects.get(issue=issue)
        assert log.minutes == 480 and log.logged_on == datetime.date(2026, 10, 1)

    def test_kind_choices_unchanged(self):
        assert IssueWorkKind.EVOLUTION == "evolution"
