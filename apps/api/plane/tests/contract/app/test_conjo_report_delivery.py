# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Activity report by e-mail (CONJO-52): business days, schedule, lock, test mode, blocks and the screen."""

# Fixtures are shared with test_conjo_billing and test_conjo_client_report (pytest injects them by name).
# ruff: noqa: F401, F811

import datetime
from decimal import Decimal
from unittest import mock

import pytest
from django.test import override_settings
from django.utils import timezone

from plane.db.models import (
    Client,
    ClientContact,
    ClientProject,
    ClientReportDelivery,
    HourLedgerEntry,
    IssueWorkKind,
    WorkspaceAreaAccess,
    WorkspaceMember,
)
from plane.utils import conjo_billing as billing
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
OUTSIDE_WINDOW = mock.patch("plane.utils.conjo_report_delivery.billing.today", return_value=datetime.date(2026, 10, 20))


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
    @LIVE
    def test_creates_the_monthly_row_once(self, ready):
        first = delivery.schedule_monthly(FIRST_BUSINESS_DAY_OF_OCT)
        again = delivery.schedule_monthly(FIRST_BUSINESS_DAY_OF_OCT + datetime.timedelta(days=1))
        assert len(first) == 1 and again == first
        row = ClientReportDelivery.objects.get()
        assert (row.period_start, row.period_end, row.trigger) == (*SEPT, ClientReportDelivery.AUTO)

    @LIVE
    def test_nothing_outside_the_window(self, ready):
        assert delivery.schedule_monthly(datetime.date(2026, 10, 20)) == []
        assert not ClientReportDelivery.objects.exists()

    @LIVE
    def test_only_active_clients_with_the_report_on(self, ready, workspace):
        Client.objects.create(workspace=workspace, name="Sem relatório")
        Client.objects.create(workspace=workspace, name="Inativo", is_active=False, monthly_report_enabled=True)
        delivery.schedule_monthly(FIRST_BUSINESS_DAY_OF_OCT)
        assert list(ClientReportDelivery.objects.values_list("client_id", flat=True)) == [ready.id]

    @LIVE
    def test_a_row_already_handled_is_not_queued_again(self, ready):
        row = auto_row(ready)
        ClientReportDelivery.objects.filter(pk=row.pk).update(status=ClientReportDelivery.SENT)
        assert delivery.schedule_monthly(FIRST_BUSINESS_DAY_OF_OCT) == []

    @LIVE
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

    @TEST
    def test_test_mode_never_creates_monthly_rows(self, ready):
        assert delivery.schedule_monthly(FIRST_BUSINESS_DAY_OF_OCT) == []
        assert not ClientReportDelivery.objects.exists()


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
        # Since MAN-467 Clients is admin-only by default; with the area, a member reads but still cannot send.
        assert api.get(self.url(workspace, ready)).status_code == 403
        WorkspaceAreaAccess.objects.create(workspace=workspace, area="clients", allowed_roles=[15])
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
    @LIVE
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


@pytest.mark.unit
class TestPdfText:
    def test_clean_keeps_punctuation_and_drops_missing_glyphs(self):
        from plane.utils.conjo_client_report_pdf import clean

        assert clean("Corrigir login (tela X ) , depois deploy . 🚀 ok") == "Corrigir login (tela X), depois deploy. ok"
        assert clean(None) == ""

    def test_pdf_with_a_huge_description(self):
        from plane.utils.conjo_client_report_pdf import render_client_report_pdf as render

        row = {
            "id": "1",
            "date": "2026-09-02",
            "key": "EXM-1",
            "kind": "maintenance",
            "title": "Título",
            "description": "palavra " * 3000,
            "minutes": 60,
            "hours": "1.00",
            "budgeted": False,
        }
        report = {
            "number": "RA-2026-09-ABCDEF",
            "issued_on": "2026-10-01",
            "period": {"from": "2026-09-01", "to": "2026-09-30"},
            "client": {"id": "x", "name": "Cliente", "legal_name": ""},
            "contract": None,
            "owner": "Conjo SA",
            "totals": {
                "minutes": 60,
                "hours": "1.00",
                "evolution_minutes": 0,
                "evolution_hours": "0",
                "maintenance_minutes": 60,
                "maintenance_hours": "1.00",
                "items": 1,
                "done_items": 0,
            },
            "package": None,
            "by_kind": [],
            "by_system": [],
            "highlights": [],
            "rows": [row],
            "next_steps": [],
            "warnings": [],
        }
        assert render(report).startswith(b"%PDF")


@pytest.mark.unit
class TestMailjetFailures:
    def send(self, effect=None, status=200):
        from plane.utils import mailjet

        response = mock.Mock(status_code=status, text="erro")
        with (
            mock.patch.object(mailjet, "is_mailjet_configured", return_value=True),
            mock.patch.object(mailjet, "get_mailjet_configuration", return_value=("k", "s", "a@b.c", "X")),
            mock.patch.object(mailjet.requests, "post", side_effect=effect, return_value=response),
        ):
            return mailjet.send_email_with_attachments(["c@d.e"], "Assunto", "<p>oi</p>")

    def test_connection_never_made_is_retried(self):
        import requests
        from urllib3.exceptions import MaxRetryError, NewConnectionError

        refused = requests.ConnectionError(MaxRetryError(None, "/", NewConnectionError(None, "refused")))
        with pytest.raises(EmailDeliveryError) as error:
            self.send(refused)
        assert error.value.retryable and not error.value.uncertain

    def test_connection_dropped_after_sending_is_uncertain(self):
        import requests

        with pytest.raises(EmailDeliveryError) as error:
            self.send(requests.ConnectionError("Connection aborted.", ConnectionResetError()))
        assert error.value.uncertain and not error.value.retryable

    @pytest.mark.parametrize(
        "status,retryable,uncertain", [(429, True, False), (502, False, True), (400, False, False)]
    )
    def test_http_answers(self, status, retryable, uncertain):
        with pytest.raises(EmailDeliveryError) as error:
            self.send(status=status)
        assert (error.value.retryable, error.value.uncertain) == (retryable, uncertain)


@pytest.mark.contract
class TestLostRows:
    def test_a_pending_row_that_lost_its_queue_message_is_queued_again(self, ready):
        from plane.bgtasks import conjo_report_task

        row = auto_row(ready)
        ClientReportDelivery.objects.filter(pk=row.pk).update(
            trigger=ClientReportDelivery.MANUAL, updated_at=timezone.now() - datetime.timedelta(hours=3)
        )
        with OUTSIDE_WINDOW, mock.patch.object(conjo_report_task.deliver_client_report, "delay") as queued:
            conjo_report_task.send_monthly_client_reports()
        queued.assert_called_once_with(str(row.id))

    def test_one_queue_failure_does_not_hold_back_the_others(self, ready, workspace):
        from plane.bgtasks import conjo_report_task

        rows = [auto_row(ready), auto_row(ready, (datetime.date(2026, 8, 1), datetime.date(2026, 8, 31)))]
        ClientReportDelivery.objects.update(updated_at=timezone.now() - datetime.timedelta(hours=3))
        with (
            OUTSIDE_WINDOW,
            mock.patch.object(
                conjo_report_task.deliver_client_report, "delay", side_effect=[Exception("broker"), None]
            ) as queued,
        ):
            conjo_report_task.send_monthly_client_reports()
        assert queued.call_count == len(rows)

    def test_invalid_contact_email_is_refused(self, session_client, workspace, client_):
        url = f"/api/workspaces/{workspace.slug}/clients/{client_.id}/contacts/"
        response = session_client.post(url, {"name": "X", "email": "não-é-email", "receives_report": True})
        assert response.status_code == 400


RATE = "plane.utils.conjo_report_delivery.get_configuration_value"


@pytest.mark.unit
class TestHourValue:
    @pytest.mark.parametrize(
        "raw,expected",
        [("150", "150"), ("150.50", "150.50"), ("1.500,50", "1500.50"), ("150,5", "150.5")],
    )
    def test_rate_formats(self, raw, expected):
        with mock.patch(RATE, return_value=(raw,)):
            assert delivery.hour_rate() == Decimal(expected)

    @pytest.mark.parametrize("raw", ["", None, "abc", "0", "-10", "NaN", "sNaN", "Infinity", "1.500", "9" * 40])
    def test_empty_or_invalid_rate_shows_no_value(self, raw):
        with mock.patch(RATE, return_value=(raw,)):
            assert delivery.hour_rate() is None
            assert delivery.report_value({"totals": {"evolution_hours": "20.00"}}) is None

    def test_only_evolution_hours_count(self):
        report = {"totals": {"evolution_hours": "20.50", "maintenance_hours": "99.00", "hours": "119.50"}}
        with mock.patch(RATE, return_value=("150.00",)):
            assert delivery.report_value(report) == {"hours": "20.50", "hour_rate": "150.00", "total": "3075.00"}

    def test_without_evolution_hours_there_is_no_value(self):
        with mock.patch(RATE, return_value=("150",)):
            assert delivery.report_value({"totals": {"evolution_hours": "0"}}) is None

    def test_money_format(self):
        from plane.utils.conjo_client_report_pdf import brl

        assert brl("3000.5") == "R$ 3.000,50"
        assert brl("1234567.89") == "R$ 1.234.567,89"
        assert brl("150") == "R$ 150,00"


@pytest.mark.contract
class TestValueInTheEmail:
    @LIVE
    def test_value_goes_in_the_email_and_the_pdf(self, ready, sent):
        reports = []
        with (
            mock.patch(RATE, return_value=("150.00",)),
            mock.patch(
                "plane.utils.conjo_report_delivery.render_client_report_pdf",
                side_effect=lambda r: reports.append(r) or render_client_report_pdf(r),
            ),
        ):
            assert delivery.deliver(auto_row(ready).id) == ClientReportDelivery.SENT
        # report_data: 3 h of evolution in September.
        html = sent.call_args.args[2]
        assert "R$ 450,00" in html and "R$ 150,00" in html
        assert reports[0]["value"]["total"] == "450.00"

    @LIVE
    def test_without_a_rate_nothing_about_money_is_shown(self, ready, sent):
        with mock.patch(RATE, return_value=("",)):
            assert delivery.deliver(auto_row(ready).id) == ClientReportDelivery.SENT
        assert "R$" not in sent.call_args.args[2]

    @LIVE
    def test_logo_goes_inside_the_message(self, ready, sent):
        with mock.patch(RATE, return_value=("",)):
            delivery.deliver(auto_row(ready).id)
        assert "cid:conjo-logo" in sent.call_args.args[2]
        ((cid, filename, mimetype, content),) = sent.call_args.kwargs["inline"]
        assert cid == "conjo-logo" and mimetype == "image/png" and content.startswith(b"\x89PNG")

    def test_client_name_is_escaped(self):
        from plane.utils.conjo_report_email import report_email

        report = {
            "number": "RA",
            "period": {"from": "2026-09-01", "to": "2026-09-30"},
            "client": {"name": "<b>X</b>", "legal_name": ""},
            "totals": {"hours": "1", "evolution_hours": "1", "maintenance_hours": "0", "done_items": 0, "items": 1},
            "package": None,
        }
        assert "<b>X</b>" not in report_email(report)[1]

    def test_mailjet_receives_the_inline_image(self):
        from plane.utils import mailjet

        with (
            mock.patch.object(mailjet, "is_mailjet_configured", return_value=True),
            mock.patch.object(mailjet, "get_mailjet_configuration", return_value=("k", "s", "a@b.c", "X")),
            mock.patch.object(mailjet.requests, "post", return_value=mock.Mock(status_code=200)) as post,
        ):
            mailjet.send_email_with_attachments(
                ["c@d.e"], "A", "<p>o</p>", inline=[("conjo-logo", "l.png", "image/png", b"x")]
            )
        message = post.call_args.kwargs["json"]["Messages"][0]
        assert message["InlinedAttachments"][0]["ContentID"] == "conjo-logo"


NOW = timezone.make_aware(datetime.datetime(2026, 9, 18, 21, 0), datetime.timezone.utc)


def empty_package(client, debit_at=NOW - datetime.timedelta(hours=3)):
    """A package whose whole balance was taken by a debit at ``debit_at``."""
    contract = make_contract(client, starts_on=datetime.date(2026, 9, 1), hours="10", months=1)
    billing.ensure_monthly_credits(contract, NOW.date())
    issue = kind(make_issue(ClientProject.objects.filter(client=client).first().project, "Grande"), "evolution")
    debit = billing.debit_for_estimate(issue, billing.balance(contract, NOW.date()), "a@b.c", on=NOW.date())
    HourLedgerEntry.objects.filter(pk=debit.pk).update(created_at=debit_at)
    return contract


@pytest.mark.contract
class TestPackageExhausted:
    @LIVE
    def test_creates_one_row_with_the_month_so_far(self, ready):
        empty_package(ready)
        ids = delivery.schedule_exhausted(NOW)
        assert len(ids) == 1
        row = ClientReportDelivery.objects.get(trigger=ClientReportDelivery.EXHAUSTED)
        assert (row.period_start, row.period_end) == (datetime.date(2026, 9, 1), datetime.date(2026, 9, 18))

    @LIVE
    def test_the_next_days_do_not_send_it_again(self, ready):
        empty_package(ready)
        delivery.schedule_exhausted(NOW)
        ClientReportDelivery.objects.update(status=ClientReportDelivery.SENT)
        assert delivery.schedule_exhausted(NOW + datetime.timedelta(days=1)) == []
        assert ClientReportDelivery.objects.count() == 1

    @LIVE
    def test_debit_after_the_run_goes_on_the_next_run(self, ready):
        empty_package(ready, debit_at=NOW + datetime.timedelta(hours=1))
        assert delivery.schedule_exhausted(NOW + datetime.timedelta(days=1)) != []

    @LIVE
    def test_package_with_balance_left_does_not_fire(self, ready):
        contract = make_contract(ready, starts_on=datetime.date(2026, 9, 1), hours="10", months=1)
        billing.ensure_monthly_credits(contract, NOW.date())
        issue = kind(make_issue(ClientProject.objects.filter(client=ready).first().project, "Pequeno"), "evolution")
        debit = billing.debit_for_estimate(issue, "2", "a@b.c", on=NOW.date())
        HourLedgerEntry.objects.filter(pk=debit.pk).update(created_at=NOW - datetime.timedelta(hours=1))
        assert delivery.schedule_exhausted(NOW) == []

    @LIVE
    def test_debit_with_no_hours_left_does_not_fire_again(self, ready):
        contract = empty_package(ready, debit_at=NOW - datetime.timedelta(days=10))
        issue = kind(make_issue(ClientProject.objects.filter(client=ready).first().project, "Excede"), "evolution")
        billing.debit_for_estimate(issue, "2", "a@b.c", on=NOW.date())
        HourLedgerEntry.objects.filter(contract=contract, hours=0).update(created_at=NOW - datetime.timedelta(hours=1))
        assert delivery.schedule_exhausted(NOW) == []

    @LIVE
    def test_expiration_after_the_debit_is_not_exhaustion(self, ready):
        contract = make_contract(ready, starts_on=datetime.date(2026, 9, 1), hours="10", months=1)
        billing.ensure_monthly_credits(contract, NOW.date())
        issue = kind(make_issue(ClientProject.objects.filter(client=ready).first().project, "Parte"), "evolution")
        debit = billing.debit_for_estimate(issue, "2", "a@b.c", on=NOW.date())
        HourLedgerEntry.objects.filter(pk=debit.pk).update(created_at=NOW - datetime.timedelta(hours=5))
        HourLedgerEntry.objects.filter(contract=contract, remaining__gt=0).update(remaining=0)
        HourLedgerEntry.objects.create(
            workspace_id=contract.workspace_id,
            contract=contract,
            kind=HourLedgerEntry.EXPIRATION,
            hours=-8,
            occurred_on=NOW.date(),
        )
        HourLedgerEntry.objects.filter(contract=contract, kind=HourLedgerEntry.EXPIRATION).update(
            created_at=NOW - datetime.timedelta(hours=1)
        )
        assert delivery.schedule_exhausted(NOW) == []

    @LIVE
    def test_period_follows_the_day_of_the_debit(self, ready):
        contract = empty_package(ready)
        HourLedgerEntry.objects.filter(contract=contract, kind=HourLedgerEntry.DEBIT).update(
            occurred_on=datetime.date(2026, 8, 31), created_at=NOW - datetime.timedelta(hours=20)
        )
        delivery.schedule_exhausted(NOW)
        row = ClientReportDelivery.objects.get(trigger=ClientReportDelivery.EXHAUSTED)
        assert (row.period_start, row.period_end) == (datetime.date(2026, 8, 1), datetime.date(2026, 8, 31))

    @LIVE
    def test_client_with_the_report_off_does_not_fire(self, ready):
        empty_package(ready)
        Client.objects.filter(pk=ready.pk).update(monthly_report_enabled=False)
        assert delivery.schedule_exhausted(NOW) == []

    @TEST
    def test_test_mode_does_not_fire(self, ready):
        empty_package(ready)
        assert delivery.schedule_exhausted(NOW) == []
        assert not ClientReportDelivery.objects.exists()

    @LIVE
    def test_email_says_the_package_ran_out(self, ready, sent):
        empty_package(ready)
        (delivery_id,) = delivery.schedule_exhausted(NOW)
        with mock.patch(RATE, return_value=("",)):
            assert delivery.deliver(delivery_id) == ClientReportDelivery.SENT
        _, subject, html, _ = sent.call_args.args
        assert subject == "Pacote de horas esgotado: Cliente Exemplo"
        assert "chegou ao fim" in html

    @LIVE
    def test_task_queues_the_rows(self, ready):
        from plane.bgtasks import conjo_report_task

        empty_package(ready, debit_at=timezone.now() - datetime.timedelta(hours=1))
        with mock.patch.object(conjo_report_task.deliver_client_report, "delay") as queued:
            conjo_report_task.send_exhausted_package_reports()
        assert queued.call_count == 1
