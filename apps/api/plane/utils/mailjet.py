# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Python imports
import base64
import logging
import os
import smtplib
import socket

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


# --------------------------------------------------------------------------- #
# Conjo: e-mail with attachments for the monthly client report (CONJO-52)
# --------------------------------------------------------------------------- #


class EmailDeliveryError(Exception):
    """The message was not handed over. ``retryable``: nothing was sent and trying again may work.
    ``uncertain``: the provider may have taken it (a timeout after the request went out), so trying again
    could send it twice."""

    def __init__(self, message, retryable=False, uncertain=False):
        super().__init__(message)
        self.retryable = retryable
        self.uncertain = uncertain


RETRYABLE_HTTP = {429, 500, 502, 503, 504}


def send_email_with_attachments(to_emails, subject, html_content, attachments=(), reply_to=None):
    """One message to every address in ``to_emails`` with ``attachments`` (``(filename, mimetype, bytes)``).

    Mailjet first, SMTP when it is not configured (like ``send_transactional_email``). Raises
    ``EmailDeliveryError`` instead of swallowing the failure, because the caller records the outcome.
    """
    to_emails = [email for email in to_emails if email]
    if not to_emails:
        raise EmailDeliveryError("Nenhum destinatário.")
    text_content = generate_plain_text_from_html(html_content)
    if is_mailjet_configured():
        return _attachments_with_mailjet(to_emails, subject, html_content, text_content, attachments, reply_to)
    return _attachments_with_smtp(to_emails, subject, html_content, text_content, attachments, reply_to)


def _attachments_with_mailjet(to_emails, subject, html_content, text_content, attachments, reply_to):
    api_key, api_secret, from_email, from_name = get_mailjet_configuration()
    message = {
        "From": {"Email": from_email, "Name": from_name},
        "To": [{"Email": email} for email in to_emails],
        "Subject": subject,
        "TextPart": text_content,
        "HTMLPart": html_content,
        "Attachments": [
            {"ContentType": mimetype, "Filename": filename, "Base64Content": base64.b64encode(content).decode()}
            for filename, mimetype, content in attachments
        ],
    }
    if reply_to:
        message["ReplyTo"] = {"Email": reply_to}
    try:
        response = requests.post(
            MAILJET_API_URL, json={"Messages": [message]}, auth=(api_key, api_secret), timeout=MAILJET_TIMEOUT * 2
        )
    except requests.ConnectionError as e:
        raise EmailDeliveryError(f"Mailjet fora do ar: {e}", retryable=True) from e
    except requests.Timeout as e:
        raise EmailDeliveryError("Mailjet não respondeu a tempo; o e-mail pode ter saído.", uncertain=True) from e
    if response.status_code >= 400:
        raise EmailDeliveryError(
            f"Mailjet recusou ({response.status_code}): {response.text[:500]}",
            retryable=response.status_code in RETRYABLE_HTTP,
        )
    logger.info(f"Report e-mail sent to {len(to_emails)} recipient(s) via Mailjet.")
    return "mailjet"


def _attachments_with_smtp(to_emails, subject, html_content, text_content, attachments, reply_to):
    host, user, password, port, use_tls, use_ssl, from_email = get_email_configuration()
    if not host:
        raise EmailDeliveryError("Nenhum servidor de e-mail configurado (Mailjet ou SMTP).")
    connection = get_connection(
        host=host,
        port=int(port),
        username=user,
        password=password,
        use_tls=use_tls == "1",
        use_ssl=use_ssl == "1",
        timeout=MAILJET_TIMEOUT * 2,
    )
    msg = EmailMultiAlternatives(
        subject=subject,
        body=text_content,
        from_email=from_email,
        to=to_emails,
        reply_to=[reply_to] if reply_to else None,
        connection=connection,
    )
    msg.attach_alternative(html_content, "text/html")
    for filename, mimetype, content in attachments:
        msg.attach(filename, content, mimetype)
    try:
        # Opening the connection (DNS, TLS, login) sends nothing, so a failure there can be retried.
        connection.open()
    except (OSError, smtplib.SMTPException) as e:
        raise EmailDeliveryError(f"Servidor de e-mail indisponível: {e}", retryable=True) from e
    try:
        msg.send()
    except smtplib.SMTPRecipientsRefused as e:
        raise EmailDeliveryError(f"Destinatários recusados: {e.recipients}") from e
    except smtplib.SMTPResponseException as e:
        raise EmailDeliveryError(
            f"Servidor de e-mail recusou ({e.smtp_code}): {e.smtp_error!r}", retryable=400 <= e.smtp_code < 500
        ) from e
    except (socket.timeout, smtplib.SMTPServerDisconnected, OSError) as e:
        raise EmailDeliveryError(f"Conexão caiu durante o envio; o e-mail pode ter saído: {e}", uncertain=True) from e
    finally:
        connection.close()
    logger.info(f"Report e-mail sent to {len(to_emails)} recipient(s) via SMTP.")
    return "smtp"
