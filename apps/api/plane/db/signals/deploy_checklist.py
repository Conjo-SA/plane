# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Deploy checklist gate.

When a work item transitions INTO the Completed state group ("Concluída" = in
production) in a project that has an enabled ``DeployChecklistTemplate``, the
transition is blocked: the state is reverted to the previous one and a comment
explains what is missing. On the first attempt the checklist sub-issues are
created so the team has them to complete (each with its proof).

Design notes:
- Keyed on the state GROUP (``completed``), so it works regardless of the state's
  display name.
- Opt-in per project: projects without an enabled template are untouched (e.g. the
  support project "Manutenções" should NOT have a template).
- FAIL-OPEN: any unexpected error is logged and the save proceeds, so a bug in the
  gate can never stop a normal issue update.
- Known limitation: the API computes activity/webhooks for the update separately, so
  the activity feed may still register the *attempted* move to Concluída even though
  it was reverted. Acceptable for now (no external webhook consumers). Move the gate
  into the issue-update view later if that phantom entry needs to be suppressed.
"""

import logging

from django.db.models.signals import pre_save
from django.dispatch import receiver

logger = logging.getLogger(__name__)

COMPLETED_GROUP = "completed"


@receiver(pre_save, sender="db.Issue", dispatch_uid="deploy_checklist_gate")
def enforce_deploy_checklist(sender, instance, **kwargs):
    try:
        _enforce(instance)
    except Exception:  # fail open — never block a normal save because of a gate bug
        logger.exception("deploy checklist gate errored; allowing the save")


def _enforce(issue):
    from django.db import transaction

    from plane.db.models import DeployChecklistTemplate, Issue, State
    from plane.db.models.deploy_checklist import DEPLOY_CHECKLIST_SOURCE

    # Only updates of a top-level work item that actually change the state.
    if issue._state.adding:
        return
    if issue.parent_id:  # never gate the checklist sub-issues themselves
        return
    if not issue.state_id or not issue.has_changed("state_id"):
        return

    # Only act when the NEW state is in the completed group and the OLD one was not.
    new_group = State.objects.filter(pk=issue.state_id).values_list("group", flat=True).first()
    if new_group != COMPLETED_GROUP:
        return

    old_state_id = issue.old_values.get("state_id")
    if not old_state_id:
        return  # no previous state to revert to; don't gate
    old_group = State.objects.filter(pk=old_state_id).values_list("group", flat=True).first()
    if old_group == COMPLETED_GROUP:
        return  # already completed; not a fresh transition

    template = DeployChecklistTemplate.objects.filter(
        project_id=issue.project_id, is_enabled=True, deleted_at__isnull=True
    ).first()
    if not template or not template.items:
        return  # project not opted in

    # Existing checklist sub-issues owned by the gate, keyed by their item index.
    children = Issue.objects.filter(
        parent_id=issue.id, external_source=DEPLOY_CHECKLIST_SOURCE, deleted_at__isnull=True
    ).select_related("state")
    existing_by_key = {c.external_id: c for c in children}

    missing_items = []  # (index, name) not created yet
    pending = []  # names still not completed (missing or incomplete)
    for idx, name in enumerate(template.items):
        child = existing_by_key.get(str(idx))
        if child is None:
            missing_items.append((idx, name))
            pending.append(name)
        elif not child.state_id or child.state.group != COMPLETED_GROUP:
            pending.append(name)

    if not pending:
        return  # every checklist item exists and is completed -> allow the completion

    # Gate fails: block the transition by reverting the state on this save.
    # Issue.save() already ran _sync_completed_at() with the NEW (completed) state
    # before this pre_save, so it stamped completed_at — clear it, since we are
    # reverting to a non-completed state (old_group != completed was checked above).
    issue.state_id = old_state_id
    issue.completed_at = None

    # Create missing sub-issues + post the explanatory comment AFTER this save commits,
    # to avoid nested-save surprises inside pre_save.
    project_id = issue.project_id
    parent_id = issue.id
    workspace_id = issue.workspace_id
    transaction.on_commit(
        lambda: _create_side_effects(parent_id, project_id, workspace_id, missing_items, pending)
    )


def _create_side_effects(parent_id, project_id, workspace_id, missing_items, pending):
    from plane.db.models import Issue, IssueComment
    from plane.db.models.deploy_checklist import DEPLOY_CHECKLIST_SOURCE

    try:
        for idx, name in missing_items:
            # State is left unset: Issue.save() assigns the project's default state.
            Issue.objects.create(
                name=name[:255],
                parent_id=parent_id,
                project_id=project_id,
                external_source=DEPLOY_CHECKLIST_SOURCE,
                external_id=str(idx),
            )

        items_html = "".join(f"<li>{name}</li>" for name in pending)
        comment_html = (
            "<p><strong>Conclusão bloqueada:</strong> conclua a checklist de deploy "
            "antes de mover para Concluída.</p>"
            f"<p>Pendências:</p><ul>{items_html}</ul>"
            "<p>Os itens estão como sub-issues deste card. Conclua cada um (com a prova) "
            "e mova o card para Concluída novamente.</p>"
        )
        IssueComment.objects.create(
            issue_id=parent_id,
            project_id=project_id,
            workspace_id=workspace_id,
            comment_html=comment_html,
            actor=None,
        )
    except Exception:
        logger.exception("deploy checklist side-effects failed for issue %s", parent_id)
