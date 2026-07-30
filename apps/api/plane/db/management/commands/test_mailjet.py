# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Python imports
import os

# Django imports
from django.core.management import BaseCommand, CommandError

# Third party imports
import requests

# Module imports
from plane.utils.mailjet import (
    MAILJET_API_URL,
    MAILJET_TIMEOUT,
    get_mailjet_configuration,
    is_mailjet_configured,
    is_smtp_configured,
)


class Command(BaseCommand):
    """Send a test email through Mailjet and print the provider response.

    Runs synchronously, so failures surface immediately instead of being
    swallowed by the Celery worker.
    """

    help = "Send a test email through Mailjet and report the provider response"

    def add_arguments(self, parser):
        parser.add_argument("to_email", type=str, help="receiver's email")

    def handle(self, *args, **options):
        receiver_email = options.get("to_email")
        if not receiver_email:
            raise CommandError("Receiver email is required")

        api_key, api_secret, from_email, from_name = get_mailjet_configuration()

        self.stdout.write("Configuration:")
        self.stdout.write(f"  MAILJET_API_KEY      : {'set' if api_key else 'MISSING'}")
        self.stdout.write(f"  MAILJET_API_SECRET   : {'set' if api_secret else 'MISSING'}")
        self.stdout.write(f"  MAILJET_FROM_EMAIL   : {from_email or 'MISSING'}")
        self.stdout.write(f"  MAILJET_FROM_NAME    : {from_name}")
        self.stdout.write(f"  SMTP fallback        : {'configured' if is_smtp_configured() else 'not configured'}")
        self.stdout.write(f"  Worker queue broker  : {'set' if os.environ.get('AMQP_URL') else 'MISSING'}")
        self.stdout.write("")

        if not is_mailjet_configured():
            self.stdout.write(
                self.style.ERROR("Mailjet is not configured. Set MAILJET_API_KEY, MAILJET_API_SECRET and MAILJET_FROM_EMAIL.")
            )
            return

        payload = {
            "Messages": [
                {
                    "From": {"Email": from_email, "Name": from_name},
                    "To": [{"Email": receiver_email}],
                    "Subject": "Teste de envio — Plane",
                    "TextPart": "Se você recebeu este e-mail, o Mailjet está configurado corretamente.",
                    "HTMLPart": "<p>Se você recebeu este e-mail, o Mailjet está configurado corretamente.</p>",
                }
            ]
        }

        self.stdout.write(f"Sending test email to {receiver_email}...")

        try:
            response = requests.post(
                MAILJET_API_URL,
                json=payload,
                auth=(api_key, api_secret),
                timeout=MAILJET_TIMEOUT,
            )
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Could not reach Mailjet: {e}"))
            return

        self.stdout.write(f"HTTP status: {response.status_code}")
        self.stdout.write(f"Response   : {response.text}")

        if response.status_code == 200:
            self.stdout.write(self.style.SUCCESS("Mailjet accepted the message."))
        elif response.status_code == 401:
            self.stdout.write(self.style.ERROR("Invalid API key or secret."))
        elif response.status_code == 400:
            self.stdout.write(
                self.style.ERROR("Mailjet rejected the payload. The sender address is usually not validated yet.")
            )
        else:
            self.stdout.write(self.style.ERROR("Mailjet returned an unexpected status."))
