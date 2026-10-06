# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""GitHub integration helpers: webhook signatures, work item keys and smart commits.

Work items are referenced the same way Jira does it: by their key (``MAN-12``) in
a branch name (``man-12-corrigir-login``), in a commit message (``MAN-12: corrige
login``, ``fix(MAN-12): ...``) or in a pull request title/body.

Smart commits (Jira syntax) are commands written after a key in a commit message:
``MAN-12 #comment texto`` adds a comment and ``MAN-12 #done`` (or any state name,
e.g. ``#em-revisao``) moves the work item.
"""

# Python imports
import hashlib
import hmac
import re
import unicodedata

# Django imports
from django.conf import settings
from django.utils.text import slugify

# Keys in commit messages and PR texts must be uppercase (as in Jira), so words
# like "utf-8" are never mistaken for work items. Branch names are usually
# lowercase, so they are matched case-insensitively.
KEY_PATTERN = r"(?<![A-Za-z0-9])([A-Z][A-Z0-9]{0,11})-(\d+)(?![0-9])"
KEY_RE_STRICT = re.compile(KEY_PATTERN)
KEY_RE_ANY_CASE = re.compile(KEY_PATTERN, re.IGNORECASE)

COMMAND_RE = re.compile(r"(?<![\w#])#([A-Za-z][\w-]*)")
COMMENT_RE = re.compile(r"(?<![\w#])#comment\b[ \t]*(.*?)(?=(?<![\w#])#[A-Za-z]|$)", re.IGNORECASE)

# Generic transition words → state group, used when no state name matches.
GROUP_ALIASES = {
    "completed": {
        "done",
        "feito",
        "feita",
        "concluido",
        "concluida",
        "concluir",
        "resolve",
        "resolved",
        "resolvido",
        "fix",
        "fixed",
        "fixes",
        "close",
        "closed",
        "closes",
        "fechar",
        "fechado",
        "finalizado",
        "finalizar",
    },
    "started": {
        "start",
        "started",
        "iniciar",
        "iniciado",
        "andamento",
        "emandamento",
        "doing",
        "progress",
        "inprogress",
        "wip",
    },
    "cancelled": {"cancel", "cancelled", "canceled", "cancelar", "cancelado", "cancelada", "wontfix"},
    "unstarted": {"todo", "afazer", "pendente"},
    "backlog": {"backlog"},
}
# Words that look like commands but are not transitions.
NON_TRANSITION_COMMANDS = {"comment", "time"}


def is_configured():
    return bool(settings.CONJO_GITHUB_WEBHOOK_SECRET)


def verify_signature(body, signature_header):
    """Validate GitHub's ``X-Hub-Signature-256`` header against the shared secret."""
    secret = settings.CONJO_GITHUB_WEBHOOK_SECRET
    if not secret or not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header[len("sha256=") :])


def find_keys(text, any_case=False):
    """Return the ordered, de-duplicated ``(IDENT, sequence)`` keys found in ``text``."""
    if not text:
        return []
    regex = KEY_RE_ANY_CASE if any_case else KEY_RE_STRICT
    keys = []
    for ident, seq in regex.findall(text):
        key = (ident.upper(), int(seq))
        if key not in keys:
            keys.append(key)
    return keys


def parse_smart_commands(message):
    """Map each key to the commands written on the same line.

    Returns ``{(IDENT, seq): {"comments": [str], "transitions": [str]}}``.
    """
    result = {}
    for line in (message or "").splitlines():
        keys = find_keys(line)
        if not keys:
            continue
        comments = [c.strip() for c in COMMENT_RE.findall(line) if c.strip()]
        transitions = [cmd for cmd in COMMAND_RE.findall(line) if cmd.lower() not in NON_TRANSITION_COMMANDS]
        if not comments and not transitions:
            continue
        for key in keys:
            entry = result.setdefault(key, {"comments": [], "transitions": []})
            entry["comments"].extend(comments)
            entry["transitions"].extend(transitions)
    return result


def normalize(text):
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", text.lower())


def resolve_state(states, command):
    """Pick the state a ``#command`` refers to, or ``None``.

    ``states`` is an iterable of objects with ``name``, ``group`` and ``sequence``.
    Order: exact name, unique partial name, then generic group words (``#done``).
    """
    states = sorted(states, key=lambda s: s.sequence)
    token = normalize(command)
    if not token:
        return None
    exact = [s for s in states if normalize(s.name) == token]
    if exact:
        return exact[0]
    partial = [s for s in states if token in normalize(s.name)]
    if len(partial) == 1:
        return partial[0]
    for group, words in GROUP_ALIASES.items():
        if token in words:
            in_group = [s for s in states if s.group == group]
            if in_group:
                return in_group[0]
    return None


def branch_name_for(identifier, sequence_id, title):
    """Suggested branch name for a work item, e.g. ``man-12-corrigir-login``."""
    slug = slugify(title or "")[:40].strip("-")
    base = f"{identifier.lower()}-{sequence_id}"
    return f"{base}-{slug}" if slug else base
