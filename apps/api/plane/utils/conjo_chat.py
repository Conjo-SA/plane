# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Minimal Matrix client used by the Conjo Chat integration.

The homeserver is a fixed, trusted URL configured through the environment, so
requests go straight through ``requests`` (no SSRF pinning, unlike webhooks).
"""

# Python imports
import logging
from urllib.parse import quote
from uuid import uuid4

# Third party imports
import requests

# Django imports
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger("plane.worker")

TIMEOUT = 10
TOKEN_CACHE_KEY = "conjo_chat:bot_token"
TOKEN_CACHE_TTL = 60 * 60 * 24 * 7
DISPLAYNAME_CACHE_KEY = "conjo_chat:bot_displayname_set"
BOT_DISPLAYNAME = "Tasks"
BOT_DEVICE_ID = "CONJO_TASKS"
PROJECT_STATE_EVENT = "br.com.conjosa.tasks.project"
WIDGET_STATE_EVENT = "im.vector.modular.widgets"
WIDGET_ID = "conjo_tasks_board"


class MatrixError(Exception):
    """A non-retryable error answered by the homeserver."""

    def __init__(self, message, status_code=None, errcode=None):
        super().__init__(message)
        self.status_code = status_code
        self.errcode = errcode


class MatrixRetryableError(MatrixError):
    """Rate limit or transient failure; ``retry_after`` is in seconds."""

    def __init__(self, message, retry_after=30, status_code=None, errcode=None):
        super().__init__(message, status_code=status_code, errcode=errcode)
        self.retry_after = max(1, int(retry_after))


def is_configured():
    return bool(settings.CONJO_CHAT_HOMESERVER_URL and settings.CONJO_CHAT_BOT_PASSWORD)


def bot_user_id():
    return f"@{settings.CONJO_CHAT_BOT_USER}:{settings.CONJO_CHAT_SERVER_NAME}"


def room_url(room_id):
    if not room_id or not settings.CONJO_CHAT_WEB_URL:
        return None
    return f"{settings.CONJO_CHAT_WEB_URL}/#/room/{room_id}"


def _q(value):
    return quote(str(value), safe="")


def _raise_for_response(response):
    try:
        data = response.json()
    except ValueError:
        data = {}
    errcode = data.get("errcode")
    error = data.get("error") or response.text[:200]

    if response.status_code == 429:
        retry_after_ms = data.get("retry_after_ms")
        if retry_after_ms is None:
            try:
                retry_after = float(response.headers.get("Retry-After", 5))
            except (TypeError, ValueError):
                retry_after = 5
        else:
            retry_after = retry_after_ms / 1000.0
        raise MatrixRetryableError(
            f"Matrix rate limit: {error}", retry_after=retry_after + 1, status_code=429, errcode=errcode
        )
    if response.status_code >= 500:
        raise MatrixRetryableError(
            f"Matrix server error {response.status_code}: {error}",
            retry_after=30,
            status_code=response.status_code,
            errcode=errcode,
        )
    raise MatrixError(
        f"Matrix error {response.status_code} {errcode or ''}: {error}".strip(),
        status_code=response.status_code,
        errcode=errcode,
    )


def _http(method, path, json=None, token=None):
    url = f"{settings.CONJO_CHAT_HOMESERVER_URL}{path}"
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        return requests.request(method, url, json=json, headers=headers, timeout=TIMEOUT)
    except requests.RequestException as e:
        raise MatrixRetryableError(f"Matrix request failed: {e}", retry_after=30) from e


def _login():
    response = _http(
        "POST",
        "/_matrix/client/v3/login",
        json={
            "type": "m.login.password",
            "identifier": {"type": "m.id.user", "user": settings.CONJO_CHAT_BOT_USER},
            "password": settings.CONJO_CHAT_BOT_PASSWORD,
            # A fixed device keeps the bot from piling up devices on every login.
            "device_id": BOT_DEVICE_ID,
            "initial_device_display_name": "Conjo Tasks",
        },
    )
    if response.status_code != 200:
        _raise_for_response(response)
    token = response.json().get("access_token")
    if not token:
        raise MatrixError("Matrix login returned no access token")
    cache.set(TOKEN_CACHE_KEY, token, TOKEN_CACHE_TTL)
    return token


def get_bot_token(force=False):
    if not is_configured():
        raise MatrixError("Conjo Chat is not configured")
    token = None if force else cache.get(TOKEN_CACHE_KEY)
    if token:
        return token
    token = _login()
    ensure_bot_displayname(token)
    return token


def ensure_bot_displayname(token=None):
    """Set the bot display name once; failures are logged and ignored."""
    if cache.get(DISPLAYNAME_CACHE_KEY):
        return
    try:
        token = token or get_bot_token()
        response = _http(
            "PUT",
            f"/_matrix/client/v3/profile/{_q(bot_user_id())}/displayname",
            json={"displayname": BOT_DISPLAYNAME},
            token=token,
        )
        if response.status_code == 200:
            cache.set(DISPLAYNAME_CACHE_KEY, True, None)
    except Exception as e:  # noqa: BLE001 - cosmetic, never block on it
        logger.warning("conjo_chat: could not set bot displayname: %s", e)


def matrix_request(method, path, json=None):
    """Authenticated request as the bot; re-logs in once on 401."""
    token = get_bot_token()
    response = _http(method, path, json=json, token=token)
    if response.status_code == 401:
        token = get_bot_token(force=True)
        response = _http(method, path, json=json, token=token)
    if response.status_code >= 400:
        _raise_for_response(response)
    try:
        return response.json()
    except ValueError:
        return {}


def board_url(project):
    return f"{settings.TASKS_PUBLIC_URL}/{project.workspace.slug}/projects/{project.id}/issues/"


def _project_room_payload(project):
    ident = project.identifier
    url = board_url(project)
    name = f"Tasks · {ident}"
    topic = f"Avisos do projeto {project.name} no Conjo Tasks"
    project_state = {
        "workspace_slug": project.workspace.slug,
        "project_id": str(project.id),
        "project_identifier": ident,
        "project_name": project.name,
        "board_url": url,
    }
    widget = {
        "type": "m.custom",
        "url": url,
        "name": f"Board · {ident}",
        "id": WIDGET_ID,
        "creatorUserId": bot_user_id(),
        "data": {},
    }
    return name, topic, project_state, widget


def _put_state(room_id, event_type, content, state_key=""):
    return matrix_request(
        "PUT",
        f"/_matrix/client/v3/rooms/{_q(room_id)}/state/{_q(event_type)}/{_q(state_key)}",
        json=content,
    )


def create_project_room(project, room_id=None):
    """Create (or refresh, when ``room_id`` is given) the project's notice room.

    Returns ``(room_id, room_name)``.
    """
    name, topic, project_state, widget = _project_room_payload(project)

    if room_id:
        try:
            _put_state(room_id, "m.room.name", {"name": name})
            _put_state(room_id, "m.room.topic", {"topic": topic})
            _put_state(room_id, PROJECT_STATE_EVENT, project_state)
            _put_state(room_id, WIDGET_STATE_EVENT, widget, state_key=WIDGET_ID)
            return room_id, name
        except MatrixRetryableError:
            raise
        except MatrixError as e:
            # The bot is no longer in the room (left, kicked or room gone):
            # fall through and create a fresh one.
            if e.status_code not in (403, 404):
                raise
            logger.warning("conjo_chat: room %s unusable (%s), creating a new one", room_id, e)

    body = {
        "name": name,
        "topic": topic,
        "preset": "public_chat",
        "visibility": "public",
        "creation_content": {"m.federate": False},
        "room_alias_name": f"tasks-{project.identifier.lower()}",
        # The bot is the room creator: Synapse already gives it power 100 (and in
        # room version 12+ creators may not appear in "users" at all).
        "power_level_content_override": {
            "events_default": 50,
            "users_default": 0,
        },
        "initial_state": [
            {"type": PROJECT_STATE_EVENT, "state_key": "", "content": project_state},
            {"type": WIDGET_STATE_EVENT, "state_key": WIDGET_ID, "content": widget},
        ],
    }
    try:
        data = matrix_request("POST", "/_matrix/client/v3/createRoom", json=body)
    except MatrixError as e:
        if e.errcode != "M_ROOM_IN_USE":
            raise
        # The alias already belongs to another room: create it without one.
        body.pop("room_alias_name")
        data = matrix_request("POST", "/_matrix/client/v3/createRoom", json=body)

    new_room_id = data.get("room_id")
    if not new_room_id:
        raise MatrixError("Matrix createRoom returned no room_id")
    return new_room_id, name


def send_html_message(room_id, html, body, txn_id=None):
    txn_id = txn_id or uuid4().hex
    return matrix_request(
        "PUT",
        f"/_matrix/client/v3/rooms/{_q(room_id)}/send/m.room.message/{_q(txn_id)}",
        json={
            "msgtype": "m.text",
            "body": body,
            "format": "org.matrix.custom.html",
            "formatted_body": html,
        },
    )
