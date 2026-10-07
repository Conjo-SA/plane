# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Realtime: tell the live server that work items of a project changed.

Events are notifications, never data: they carry only ids, field names and the
actor. Browsers that receive one refetch the work item through the normal,
authenticated REST API, so permissions keep being enforced by the API.

Publishing is fire-and-forget: a POST to the live server's internal endpoint,
authenticated with ``LIVE_SERVER_SECRET_KEY``, with a short timeout. Any failure
is only logged at debug level and never breaks the caller.
"""

# Python imports
import logging
import os
import threading
import time

# Third party imports
import requests

# Django imports
from django.db import connection, transaction

logger = logging.getLogger("plane.realtime")

PUBLISH_PATH = "/live/realtime/publish"
PUBLISH_TIMEOUT_SECONDS = 1.0
MAX_ISSUE_IDS = 500
MAX_FIELDS = 50


def _publish_url():
    base = (os.environ.get("LIVE_INTERNAL_URL") or "http://live:3000").strip().rstrip("/")
    return f"{base}{PUBLISH_PATH}"


def _secret():
    return (os.environ.get("LIVE_SERVER_SECRET_KEY") or "").strip()


def _clean_ids(values):
    ids = []
    seen = set()
    for value in values or []:
        if not value:
            continue
        value = str(value)
        if value in seen:
            continue
        seen.add(value)
        ids.append(value)
        if len(ids) >= MAX_ISSUE_IDS:
            break
    return ids


def _issue_creators(issue_ids):
    """created_by of each work item, so the live server can keep restricted guests to their own items.

    Never sent to browsers: the live server strips it before broadcasting.
    """
    if not issue_ids:
        return {}
    try:
        from plane.db.models import Issue

        rows = Issue.all_objects.filter(pk__in=issue_ids).values_list("id", "created_by_id")
        return {str(issue_id): str(creator_id) for issue_id, creator_id in rows if creator_id}
    except Exception as e:  # pragma: no cover - defensive
        logger.debug("realtime: could not resolve creators: %s", e)
        return {}


def build_event(event_type, workspace_slug, project_id, issue_ids=None, actor_id=None, fields=None):
    issue_ids = _clean_ids(issue_ids)
    return {
        "type": str(event_type)[:64],
        "workspace_slug": str(workspace_slug or ""),
        "project_id": str(project_id),
        "issue_ids": issue_ids,
        "actor_id": str(actor_id) if actor_id else None,
        "fields": sorted({str(field)[:64] for field in (fields or []) if field})[:MAX_FIELDS],
        "ts": int(time.time() * 1000),
        "issue_creators": _issue_creators(issue_ids),
    }


def send_event(payload):
    """POST one event to the live server. Returns True when it was accepted."""
    secret = _secret()
    if not secret:
        return False
    try:
        response = requests.post(
            _publish_url(),
            json=payload,
            headers={"live-server-secret-key": secret},
            timeout=PUBLISH_TIMEOUT_SECONDS,
        )
        if response.status_code >= 300:
            logger.debug("realtime: live server answered %s", response.status_code)
            return False
        return True
    except Exception as e:
        logger.debug("realtime: publish failed: %s", e)
        return False


def _send_in_background(payload):
    thread = threading.Thread(target=send_event, args=(payload,), name="realtime-publish", daemon=True)
    thread.start()


def publish_project_event(
    event_type,
    project_id,
    issue_ids=None,
    actor_id=None,
    fields=None,
    workspace_slug=None,
    background=True,
):
    """Notify everyone looking at a project that some of its work items changed.

    From request code (``background=True``) the event is sent after the current
    transaction commits, on a short-lived thread, so the response is never delayed
    and browsers never refetch data that is not committed yet. Background tasks can
    pass ``background=False`` to send it inline. Never raises.
    """
    try:
        if not project_id or not _secret():
            return
        if not workspace_slug:
            from plane.db.models import Project

            workspace_slug = (
                Project.objects.filter(pk=project_id).values_list("workspace__slug", flat=True).first() or ""
            )

        def _publish():
            try:
                payload = build_event(event_type, workspace_slug, project_id, issue_ids, actor_id, fields)
                if background:
                    _send_in_background(payload)
                else:
                    send_event(payload)
            except Exception as e:  # pragma: no cover - defensive
                logger.debug("realtime: could not publish: %s", e)

        if connection.in_atomic_block:
            transaction.on_commit(_publish)
        else:
            _publish()
    except Exception as e:
        logger.debug("realtime: could not schedule publish: %s", e)
