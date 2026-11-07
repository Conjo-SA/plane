# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Client activity report by e-mail (CONJO-52): the daily check and the delivery of each e-mail."""

# Third party imports
from celery import shared_task

# Module imports
from plane.utils import conjo_report_delivery as delivery
from plane.utils.exception_logger import log_exception


@shared_task
def send_monthly_client_reports():
    """Daily: on the first business day (and a few days after, to catch up) queue the monthly reports."""
    try:
        delivery.release_stuck()
        queue = delivery.schedule_monthly() + delivery.lost_pending()
    except Exception as e:
        log_exception(e)
        return
    # Queuing a row twice is harmless (only a pending row is sent); one failure must not hold back the rest.
    for delivery_id in dict.fromkeys(queue):
        try:
            deliver_client_report.delay(delivery_id)
        except Exception as e:
            log_exception(e)


@shared_task(bind=True, max_retries=delivery.MAX_ATTEMPTS)
def deliver_client_report(self, delivery_id):
    if delivery.deliver(delivery_id) == delivery.RETRY:
        raise self.retry(countdown=delivery.RETRY_MINUTES * 60)
