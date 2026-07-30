# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Python imports
import hashlib
import secrets
from datetime import timedelta

# Django imports
from django.contrib.auth.hashers import check_password, make_password
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.utils import timezone

# Module imports
from plane.db.models import IntakePortalSession, IntakePortalVerification

CODE_TTL_MINUTES = 10
CODE_MAX_ATTEMPTS = 5
CODE_RESEND_COOLDOWN_SECONDS = 60
SESSION_TTL_DAYS = 7
PORTAL_TOKEN_HEADER = "X-Portal-Token"


def normalize_email(raw_email):
    """Return a normalized email or None when it is not a valid address."""
    email = (raw_email or "").strip().lower()
    if not email:
        return None
    try:
        validate_email(email)
    except ValidationError:
        return None
    return email


def hash_token(token):
    """Hash a session token. Tokens are high entropy, so a fast digest is enough."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_verification_code():
    """Return a 6 digit code generated from a cryptographically secure source."""
    return f"{secrets.randbelow(1_000_000):06d}"


def is_on_cooldown(email, workspace_id):
    """Prevent a requester from flooding an inbox with codes."""
    cutoff = timezone.now() - timedelta(seconds=CODE_RESEND_COOLDOWN_SECONDS)
    return IntakePortalVerification.objects.filter(
        email=email, workspace_id=workspace_id, created_at__gte=cutoff
    ).exists()


def create_verification(email, workspace_id, project_id=None):
    """Invalidate previous codes and issue a new one. Returns the plain code."""
    IntakePortalVerification.objects.filter(email=email, workspace_id=workspace_id, is_used=False).update(is_used=True)

    code = generate_verification_code()
    IntakePortalVerification.objects.create(
        email=email,
        workspace_id=workspace_id,
        project_id=project_id,
        code_hash=make_password(code),
        expires_at=timezone.now() + timedelta(minutes=CODE_TTL_MINUTES),
    )
    return code


def verify_code(email, workspace_id, code):
    """Validate a submitted code. Returns (is_valid, error_message)."""
    verification = (
        IntakePortalVerification.objects.filter(
            email=email, workspace_id=workspace_id, is_used=False, expires_at__gt=timezone.now()
        )
        .order_by("-created_at")
        .first()
    )

    if verification is None:
        return False, "Código expirado ou inexistente. Solicite um novo código."

    if verification.attempts >= CODE_MAX_ATTEMPTS:
        verification.is_used = True
        verification.save(update_fields=["is_used"])
        return False, "Muitas tentativas. Solicite um novo código."

    if not check_password((code or "").strip(), verification.code_hash):
        verification.attempts += 1
        verification.save(update_fields=["attempts"])
        return False, "Código inválido."

    verification.is_used = True
    verification.save(update_fields=["is_used"])
    return True, None


def create_session(email, workspace_id, project_id=None):
    """Issue an opaque session token. Only its digest is stored."""
    token = secrets.token_urlsafe(48)
    IntakePortalSession.objects.create(
        email=email,
        workspace_id=workspace_id,
        project_id=project_id,
        token_hash=hash_token(token),
        expires_at=timezone.now() + timedelta(days=SESSION_TTL_DAYS),
    )
    return token


def resolve_session(request, workspace_id=None):
    """Return the active session for the request token, or None."""
    token = request.headers.get(PORTAL_TOKEN_HEADER)
    if not token:
        return None

    queryset = IntakePortalSession.objects.filter(token_hash=hash_token(token), expires_at__gt=timezone.now())
    if workspace_id:
        queryset = queryset.filter(workspace_id=workspace_id)

    session = queryset.first()
    if session is None:
        return None

    session.last_used_at = timezone.now()
    session.save(update_fields=["last_used_at"])
    return session
