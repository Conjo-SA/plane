# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Python imports
import logging
import os

# Django imports
from django.core.mail import EmailMultiAlternatives, get_connection

# Third party imports
import requests

# Module imports
from plane.license.utils.instance_value import get_email_configuration
from plane.utils.email import generate_plain_text_from_html
from plane.utils.exception_logger import log_exception

MAILJET_API_URL = "https://api.mailjet.com/v3.1/send"
MAILJET_TIMEOUT = 15

logger = logging.getLogger("plane.worker")


def get_mailjet_configuration():
    """Return the Mailjet credentials configured through environment variables."""
    return (
        os.environ.get("MAILJET_API_KEY"),
        os.environ.get("MAILJET_API_SECRET"),
        os.environ.get("MAILJET_FROM_EMAIL"),
        os.environ.get("MAILJET_FROM_NAME", "Suporte"),
    )


def is_mailjet_configured():
    api_key, api_secret, from_email, _ = get_mailjet_configuration()
    return bool(api_key and api_secret and from_email)


def is_smtp_configured():
    (EMAIL_HOST, *_rest) = get_email_configuration()
    return bool(EMAIL_HOST)


def is_email_provider_configured():
    """True when at least one delivery channel is usable."""
    return is_mailjet_configured() or is_smtp_configured()


def _send_with_mailjet(to_email, subject, html_content, text_content):
    api_key, api_secret, from_email, from_name = get_mailjet_configuration()

    payload = {
        "Messages": [
            {
                "From": {"Email": from_email, "Name": from_name},
                "To": [{"Email": to_email}],
                "Subject": subject,
                "TextPart": text_content,
                "HTMLPart": html_content,
            }
        ]
    }

    response = requests.post(
        MAILJET_API_URL,
        json=payload,
        auth=(api_key, api_secret),
        timeout=MAILJET_TIMEOUT,
    )
    response.raise_for_status()
    return True


def _send_with_smtp(to_email, subject, html_content, text_content):
    (
        EMAIL_HOST,
        EMAIL_HOST_USER,
        EMAIL_HOST_PASSWORD,
        EMAIL_PORT,
        EMAIL_USE_TLS,
        EMAIL_USE_SSL,
        EMAIL_FROM,
    ) = get_email_configuration()

    if not EMAIL_HOST:
        logger.warning("Transactional email skipped: no SMTP host and no Mailjet credentials configured.")
        return False

    connection = get_connection(
        host=EMAIL_HOST,
        port=int(EMAIL_PORT),
        username=EMAIL_HOST_USER,
        password=EMAIL_HOST_PASSWORD,
        use_tls=EMAIL_USE_TLS == "1",
        use_ssl=EMAIL_USE_SSL == "1",
    )

    msg = EmailMultiAlternatives(
        subject=subject,
        body=text_content,
        from_email=EMAIL_FROM,
        to=[to_email],
        connection=connection,
    )
    msg.attach_alternative(html_content, "text/html")
    msg.send()
    return True


def send_transactional_email(to_email, subject, html_content):
    """Send a transactional email, preferring Mailjet and falling back to SMTP.

    Returns True when the message was handed over to a provider.
    """
    if not to_email:
        return False

    text_content = generate_plain_text_from_html(html_content)

    try:
        if is_mailjet_configured():
            _send_with_mailjet(to_email, subject, html_content, text_content)
            logger.info(f"Transactional email sent to {to_email} via Mailjet.")
            return True

        if _send_with_smtp(to_email, subject, html_content, text_content):
            logger.info(f"Transactional email sent to {to_email} via SMTP.")
            return True
        return False
    except requests.HTTPError as e:
        # Mailjet returns the rejection reason in the body, which is what tells
        # apart an invalid key from an unverified sender address.
        response_body = e.response.text if e.response is not None else ""
        logger.error(f"Mailjet rejected the message for {to_email}: {response_body}")
        log_exception(e)
        return False
    except Exception as e:
        logger.error(f"Failed to deliver transactional email to {to_email}.")
        log_exception(e)
        return False
