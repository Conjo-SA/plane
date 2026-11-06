# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Activity report by e-mail (CONJO-52): business days, schedule, lock, test mode, blocks and the screen."""

# Fixtures are shared with test_conjo_billing and test_conjo_client_report (pytest injects them by name).
# ruff: noqa: F401, F811

import datetime
from unittest import mock

import pytest
from django.test import override_settings
from django.utils import timezone

from plane.db.models import (
    Client,
    ClientContact,
    ClientProject,
    ClientReportDelivery,
    IssueWorkKind,
    WorkspaceMember,
)
from plane.utils import conjo_report_delivery as delivery
from plane.utils.conjo_business_days import easter, first_business_day, is_business_day
from plane.utils.conjo_client_report_pdf import render_client_report_pdf
from plane.utils.mailjet import EmailDeliveryError

from .test_conjo_billing import client_, make_contract, make_issue, project
from .test_conjo_client_report import api_for, kind, log, report_data

SEPT = (datetime.date(2026, 9, 1), datetime.date(2026, 9, 30))
FIRST_BUSINESS_DAY_OF_OCT = datetime.date(2026, 10, 1)
LIVE = override_settings(CONJO_REPORT_MODE="live", CONJO_REPORT_TEST_EMAIL="")
TEST = override_settings(CONJO_REPORT_MODE="test", CONJO_REPORT_TEST_EMAIL="teste@conjosa.com.br")


@pytest.fixture(autouse=True)
def no_chat():
    with mock.patch("plane.utils.conjo_report_delivery.alert_team") as alert:
        yield alert


@pytest.fixture
def sent():
    with mock.patch("plane.utils.conjo_report_delivery.send_email_with_attachments") as send:
        yield send


@pytest.fixture
def ready(client_, report_data):
    """The September report of ``client_`` ready to go: the item without kind classified, Maria receives."""
    kind(report_data["loose"], IssueWorkKind.MAINTENANCE)
    Client.objects.filter(pk=client_.pk).update(monthly_report_enabled=True)
    ClientContact.objects.filter(client=client_).update(receives_report=True)
    client_.refresh_from_db()
    return client_


def auto_row(client, period=SEPT):
    return ClientReportDelivery.objects.create(
        client=client, workspace_id=client.workspace_id, period_start=period[0], period_end=period[1]
    )


@pytest.mark.unit
class TestBusinessDays:
    def test_easter(self):
        assert easter(2026) == datetime.date(2026, 4, 5)
        assert easter(2027) == datetime.date(2027, 3, 28)

    @pytest.mark.parametrize(
        "year,month,expected",
        [
            (2026, 10, datetime.date(2026, 10, 1)),  # Thursday
            (2026, 11, datetime.date(2026, 11, 3)),  # 1st Sunday, 2nd Finados
            (2027, 1, datetime.date(2027, 1, 4)),  # 1st holiday (Friday), then the weekend
            (2026, 5, datetime.date(2026, 5, 4)),  # 1st Labour Day (Friday)
            (2026, 8, datetime.date(2026, 8, 3)),  # 1st Saturday
        ],
    )
    def test_first_business_day(self, year, month, expected):
        assert first_business_day(year, month) == expected

    def test_carnival_and_local_holidays_are_not_business_days(self):
        assert not is_business_day(datetime.date(2026, 2, 16))  # Carnival Monday
        assert not is_business_day(datetime.date(2026, 3, 19))  # São José (Ceará)
        assert not is_business_day(datetime.date(2026, 8, 14 + 1))  # Assunção (Fortaleza), a Saturday anyway
        assert not is_business_day(datetime.date(2027, 3, 25))  # Data Magna do Ceará, a Thursday
        assert is_business_day(datetime.date(2027, 3, 24))

    def test_monthly_window(self):
        assert not delivery.monthly_due(datetime.date(2026, 11, 2))
        assert delivery.monthly_due(datetime.date(2026, 11, 3))
        assert delivery.monthly_due(datetime.date(2026, 11, 6))
        assert not delivery.monthly_due(datetime.date(2026, 11, 7))
        assert delivery.previous_month(datetime.date(2026, 11, 3)) == (
            datetime.date(2026, 10, 1),
            datetime.date(2026, 10, 31),
        )


@pytest.mark.contract
class TestSchedule:
    def test_creates_the_monthly_row_once(self, ready):
        first = delivery.schedule_monthly(FIRST_BUSINESS_DAY_OF_OCT)
        again = delivery.schedule_monthly(FIRST_BUSINESS_DAY_OF_OCT + datetime.timedelta(days=1))
        assert len(first) == 1 and again == first
        row = ClientReportDelivery.objects.get()
        assert (row.period_start, row.period_end, row.trigger) == (*SEPT, ClientReportDelivery.AUTO)

    def test_nothing_outside_the_window(self, ready):
        assert delivery.schedule_monthly(datetime.date(2026, 10, 20)) == []
        assert not ClientReportDelivery.objects.exists()

    def test_only_active_clients_with_the_report_on(self, ready, workspace):
        Client.objects.create(workspace=workspace, name="Sem relatório")
        Client.objects.create(workspace=workspace, name="Inativo", is_active=False, monthly_report_enabled=True)
        delivery.schedule_monthly(FIRST_BUSINESS_DAY_OF_OCT)
        assert list(ClientReportDelivery.objects.values_list("client_id", flat=True)) == [ready.id]

    def test_a_row_already_handled_is_not_queued_again(self, ready):
        row = auto_row(ready)
        ClientReportDelivery.objects.filter(pk=row.pk).update(status=ClientReportDelivery.SENT)
        assert delivery.schedule_monthly(FIRST_BUSINESS_DAY_OF_OCT) == []

    def test_a_row_stuck_in_sending_fails_and_is_never_resent(self, ready, no_chat):
        row = auto_row(ready)
        ClientReportDelivery.objects.filter(pk=row.pk).update(
            status=ClientReportDelivery.SENDING, updated_at=timezone.now() - datetime.timedelta(hours=2)
        )
        assert [r.pk for r in delivery.release_stuck()] == [row.pk]
        row.refresh_from_db()
        assert row.status == ClientReportDelivery.FAILED
        assert no_chat.called
        assert delivery.schedule_monthly(FIRST_BUSINESS_DAY_OF_OCT) == []


@pytest.mark.contract
class TestDeliver:
    @LIVE
    def test_sends_once_to_the_marked_contacts(self, ready, sent):
        row = auto_row(ready)
        assert delivery.deliver(row.id) == ClientReportDelivery.SENT
        assert delivery.deliver(row.id) is None
        assert sent.call_count == 1
        to, subject, html, attachments = sent.call_args.args
        assert to == ["maria@cliente.com.br"]
        assert "Cliente Exemplo" in subject and "Setembro de 2026" in subject
        (filename, mimetype, pdf) = attachments[0]
        assert filename.endswith(".pdf") and mimetype == "application/pdf" and pdf.startswith(b"%PDF")
        row.refresh_from_db()
        assert row.status == ClientReportDelivery.SENT and row.sent_at and not row.test_mode
        assert row.delivered_to == ["maria@cliente.com.br"] and row.number.startswith("RA-2026-09-")

    @TEST
    def test_outside_production_only_the_test_address_gets_it(self, ready, sent):
        row = auto_row(ready)
        assert delivery.deliver(row.id) == ClientReportDelivery.SENT
        to, subject, html, _ = sent.call_args.args
        assert to == ["teste@conjosa.com.br"]
        assert subject.startswith("[TESTE]") and "maria@cliente.com.br" in html
        row.refresh_from_db()
        assert row.test_mode and row.delivered_to == ["teste@conjosa.com.br"]
        assert row.recipients == ["maria@cliente.com.br"]

    @override_settings(CONJO_REPORT_MODE="test", CONJO_REPORT_TEST_EMAIL="")
    def test_outside_production_without_test_address_nothing_goes(self, ready, sent):
        row = auto_row(ready)
        assert delivery.deliver(row.id) == ClientReportDelivery.SKIPPED
        assert not sent.called

    @LIVE
    def test_item_without_kind_blocks_and_tells_the_team(self, client_, report_data, sent, no_chat):
        ClientContact.objects.filter(client=client_).update(receives_report=True)
        Client.objects.filter(pk=client_.pk).update(monthly_report_enabled=True)
        row = auto_row(client_)
        assert delivery.deliver(row.id) == ClientReportDelivery.SKIPPED
        assert not sent.called
        row.refresh_from_db()
        assert "sem tipo" in row.reason and no_chat.called

    @LIVE
    def test_without_recipients_tells_the_team(self, ready, sent, no_chat):
        ClientContact.objects.filter(client=ready).update(receives_report=False)
        row = auto_row(ready)
        assert delivery.deliver(row.id) == ClientReportDelivery.SKIPPED
        assert not sent.called and no_chat.called

    @LIVE
    def test_without_activity_and_package_it_is_skipped(self, ready, sent):
        row = auto_row(ready, (datetime.date(2026, 6, 1), datetime.date(2026, 6, 30)))
        assert delivery.deliver(row.id) == ClientReportDelivery.SKIPPED
        assert not sent.called

    @LIVE
    def test_without_activity_but_with_package_it_goes(self, ready, sent):
        make_contract(ready, starts_on=datetime.date(2026, 5, 1))
        row = auto_row(ready, (datetime.date(2026, 6, 1), datetime.date(2026, 6, 30)))
        assert delivery.deliver(row.id) == ClientReportDelivery.SENT

    @LIVE
    def test_monthly_row_of_a_client_turned_off_is_skipped(self, ready, sent):
        row = auto_row(ready)
        Client.objects.filter(pk=ready.pk).update(monthly_report_enabled=False)
        assert delivery.deliver(row.id) == ClientReportDelivery.SKIPPED
        assert not sent.called

    @LIVE
    def test_temporary_failure_is_retried_then_fails(self, ready, sent, no_chat):
        sent.side_effect = EmailDeliveryError("fora do ar", retryable=True)
        row = auto_row(ready)
        for _ in range(delivery.MAX_ATTEMPTS - 1):
            assert delivery.deliver(row.id) == delivery.RETRY
            row.refresh_from_db()
            assert row.status == ClientReportDelivery.PENDING
            assert not no_chat.called
        assert delivery.deliver(row.id) == ClientReportDelivery.FAILED
        row.refresh_from_db()
        assert row.attempts == delivery.MAX_ATTEMPTS and no_chat.called

    @LIVE
    def test_uncertain_failure_is_not_retried(self, ready, sent):
        sent.side_effect = EmailDeliveryError("timeout", uncertain=True)
        row = auto_row(ready)
        assert delivery.deliver(row.id) == ClientReportDelivery.FAILED
        row.refresh_from_db()
        assert "Confira com o cliente" in row.reason

    @LIVE
    def test_a_client_never_gets_data_of_another(self, ready, workspace, project, sent):
        other = Client.objects.create(workspace=workspace, name="Outro Cliente", monthly_report_enabled=True)
        ClientContact.objects.create(
            workspace=workspace, client=other, name="João", email="joao@outro.com.br", receives_report=True
        )
        from plane.db.models import IssueClient, Project

        other_project = Project.objects.create(name="Outro", identifier="OUT", workspace=workspace)
        ClientProject.objects.create(workspace=workspace, client=other, project=other_project)
        secret = kind(make_issue(other_project, "Projeto confidencial do outro"), IssueWorkKind.EVOLUTION)
        log(secret, 240, datetime.date(2026, 9, 15), "Detalhe sigiloso")
        # A card of the other client on the first client's board.
        shared = kind(make_issue(project, "Card do outro no board"), IssueWorkKind.EVOLUTION)
        IssueClient.objects.create(issue=shared, client=other, project=project, workspace=workspace)
        log(shared, 30, datetime.date(2026, 9, 16), "Também sigiloso")

        reports = []
        with mock.patch(
            "plane.utils.conjo_report_delivery.render_client_report_pdf",
            side_effect=lambda r: reports.append(r) or render_client_report_pdf(r),
        ):
            assert delivery.deliver(auto_row(ready).id) == ClientReportDelivery.SENT
            assert delivery.deliver(auto_row(other).id) == ClientReportDelivery.SENT
        mine, theirs = reports
        assert sent.call_args_list[0].args[0] == ["maria@cliente.com.br"]
        assert sent.call_args_list[1].args[0] == ["joao@outro.com.br"]
        my_titles = {row["title"] for row in mine["rows"]}
        assert "Projeto confidencial do outro" not in my_titles and "Card do outro no board" not in my_titles
        assert {row["title"] for row in theirs["rows"]} == {"Projeto confidencial do outro", "Card do outro no board"}
        assert "sigiloso" not in str(mine) and "Lembrete" not in str(theirs)


@pytest.mark.contract
class TestDeliveriesEndpoint:
    def url(self, workspace, client):
        return f"/api/workspaces/{workspace.slug}/clients/{client.id}/report/deliveries/"

    def test_admin_sends_by_hand_and_sees_the_history(self, session_client, workspace, ready):
        with mock.patch("plane.bgtasks.conjo_report_task.deliver_client_report.delay") as queued:
            with self.captureOnCommit():
                response = session_client.post(
                    self.url(workspace, ready), {"from": "2026-09-01", "to": "2026-09-30"}, format="json"
                )
        assert response.status_code == 202
        assert response.data["trigger"] == "manual" and response.data["status"] == "pending"
        queued.assert_called_once_with(response.data["id"])
        listing = session_client.get(self.url(workspace, ready))
        assert listing.status_code == 200
        assert listing.data["recipients"] == ["maria@cliente.com.br"]
        assert [d["id"] for d in listing.data["deliveries"]] == [response.data["id"]]

    @staticmethod
    def captureOnCommit():
        return mock.patch("django.db.transaction.on_commit", side_effect=lambda fn, *a, **k: fn())

    def test_member_sees_but_cannot_send(self, workspace, ready):
        api = api_for(workspace, "membro@conjosa.com.br", 15)
        assert api.get(self.url(workspace, ready)).status_code == 200
        response = api.post(self.url(workspace, ready), {"from": "2026-09-01", "to": "2026-09-30"}, format="json")
        assert response.status_code == 403

    def test_needs_a_recipient_and_a_closed_period(self, session_client, workspace, ready):
        tomorrow = (timezone.localdate() + datetime.timedelta(days=1)).isoformat()
        response = session_client.post(self.url(workspace, ready), {"from": "2026-09-01", "to": tomorrow})
        assert response.status_code == 400
        ClientContact.objects.filter(client=ready).update(receives_report=False)
        response = session_client.post(self.url(workspace, ready), {"from": "2026-09-01", "to": "2026-09-30"})
        assert response.status_code == 400
        assert not ClientReportDelivery.objects.exists()

    def test_contact_that_receives_needs_an_email(self, session_client, workspace, client_):
        url = f"/api/workspaces/{workspace.slug}/clients/{client_.id}/contacts/"
        response = session_client.post(url, {"name": "Sem e-mail", "receives_report": True}, format="json")
        assert response.status_code == 400
        response = session_client.post(
            url, {"name": "Com e-mail", "email": "ok@cliente.com.br", "receives_report": True}, format="json"
        )
        assert response.status_code == 201 and response.data["receives_report"] is True

    def test_client_turns_the_monthly_report_on(self, session_client, workspace, client_):
        url = f"/api/workspaces/{workspace.slug}/clients/{client_.id}/"
        response = session_client.patch(url, {"monthly_report_enabled": True}, format="json")
        assert response.status_code == 200 and response.data["monthly_report_enabled"] is True
        client_.refresh_from_db()
        assert client_.monthly_report_enabled


@pytest.mark.contract
class TestTasks:
    def test_daily_task_queues_the_pending_rows(self, ready):
        from plane.bgtasks import conjo_report_task

        with (
            mock.patch("plane.utils.conjo_report_delivery.billing.today", return_value=FIRST_BUSINESS_DAY_OF_OCT),
            mock.patch.object(conjo_report_task.deliver_client_report, "delay") as queued,
        ):
            conjo_report_task.send_monthly_client_reports()
        row = ClientReportDelivery.objects.get()
        queued.assert_called_once_with(str(row.id))

    @LIVE
    def test_delivery_task_asks_for_a_retry(self, ready, sent):
        from celery.exceptions import Retry

        from plane.bgtasks import conjo_report_task

        sent.side_effect = EmailDeliveryError("fora do ar", retryable=True)
        row = auto_row(ready)
        task = conjo_report_task.deliver_client_report
        with mock.patch.object(task, "retry", side_effect=Retry()) as retry, pytest.raises(Retry):
            task(str(row.id))
        retry.assert_called_once_with(countdown=delivery.RETRY_MINUTES * 60)
