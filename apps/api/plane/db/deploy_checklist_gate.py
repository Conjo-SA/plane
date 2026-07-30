# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Deploy checklist gate (API layer).

Evaluated in the issue update view BEFORE saving. When a work item is being moved
INTO the Completed state group ("Concluída" = production) in a project where
``Project.deploy_checklist_enabled`` is on (toggle in Project Settings > Automations),
the checklist sub-issues are ensured to exist and the list of still-pending items is
returned so the view can reject the update with a 400 (the board then rolls the card
back and shows the message).

Doing this in the view (instead of a model signal) means the rejection reaches the
client as a normal 400 — the optimistic UI update is undone automatically — and no
phantom "moved to Concluída" activity is recorded, because nothing is saved.

FAIL-OPEN: any unexpected error returns [] so a bug here can never block an update.
"""

import logging

logger = logging.getLogger(__name__)

COMPLETED_GROUP = "completed"


def evaluate_deploy_checklist(issue, new_state_id):
    """Return the list of pending checklist item names that block completing ``issue``.

    Returns [] when the move is allowed (not entering completed, project not opted in,
    or every checklist item already completed). Creates any missing checklist
    sub-issues as a side effect so the team has them to complete.
    """
    try:
        return _evaluate(issue, new_state_id)
    except Exception:
        logger.exception("deploy checklist gate errored; allowing the update")
        return []


def _evaluate(issue, new_state_id):
    from plane.db.models import Issue, Project, State
    from plane.db.models.deploy_checklist import DEFAULT_DEPLOY_CHECKLIST_ITEMS, DEPLOY_CHECKLIST_SOURCE

    if not new_state_id:
        return []
    if issue.parent_id:  # never gate the checklist sub-issues themselves
        return []

    new_group = State.objects.filter(pk=new_state_id).values_list("group", flat=True).first()
    if new_group != COMPLETED_GROUP:
        return []

    old_group = (
        State.objects.filter(pk=issue.state_id).values_list("group", flat=True).first()
        if issue.state_id
        else None
    )
    if old_group == COMPLETED_GROUP:
        return []  # already completed; not a fresh transition

    enabled = (
        Project.objects.filter(pk=issue.project_id).values_list("deploy_checklist_enabled", flat=True).first()
    )
    if not enabled:
        return []  # project not opted in (toggle off in Project Settings > Automations)
    items = DEFAULT_DEPLOY_CHECKLIST_ITEMS

    children = Issue.objects.filter(
        parent_id=issue.id, external_source=DEPLOY_CHECKLIST_SOURCE, deleted_at__isnull=True
    ).select_related("state")
    existing_by_key = {c.external_id: c for c in children}

    missing_items = []  # (index, name) not created yet
    pending = []  # names still not completed (missing or incomplete)
    for idx, name in enumerate(items):
        child = existing_by_key.get(str(idx))
        if child is None:
            missing_items.append((idx, name))
            pending.append(name)
        elif not child.state_id or child.state.group != COMPLETED_GROUP:
            pending.append(name)

    if not pending:
        return []  # every checklist item exists and is completed -> allow

    # Create the missing checklist sub-issues. State is left unset so Issue.save()
    # assigns the project's default state (a non-completed, "pending" state).
    for idx, name in missing_items:
        Issue.objects.create(
            name=name[:255],
            parent_id=issue.id,
            project_id=issue.project_id,
            external_source=DEPLOY_CHECKLIST_SOURCE,
            external_id=str(idx),
        )

    return pending
