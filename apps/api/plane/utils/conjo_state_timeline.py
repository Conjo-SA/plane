# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Time a work item spent in each state (board column), rebuilt from its state-change history.

The history (IssueActivity, field "state") records every move with the old and the new state. The card
starts in the old state of its first move (or in its current state when it never moved) at creation time.
The clock stops when the card reaches a completed or cancelled state: that last state is returned as the
end point, with no duration.
"""

# Django imports
from django.utils import timezone

# Module imports
from plane.db.models import IntakeIssue, IssueActivity, State, StateGroup

TERMINAL_GROUPS = (StateGroup.COMPLETED.value, StateGroup.CANCELLED.value)
UNKNOWN_COLOR = "#9AA4BC"


def _state_info(states, state_id, fallback_name):
    state = states.get(state_id) if state_id else None
    if state is not None:
        return {
            "state_id": str(state.id),
            "name": state.name,
            "color": state.color or UNKNOWN_COLOR,
            "group": state.group,
        }
    return {
        "state_id": str(state_id) if state_id else None,
        "name": fallback_name or "Estado removido",
        "color": UNKNOWN_COLOR,
        "group": None,
    }


def build_state_timeline(issue, now=None):
    now = now or timezone.now()
    # Every state of the project, triage and removed ones included: old moves may point at them.
    states = {s.id: s for s in State.all_state_objects.filter(project_id=issue.project_id)}
    moves = list(
        IssueActivity.objects.filter(issue_id=issue.id, field="state", deleted_at__isnull=True)
        .order_by("created_at")
        .values("created_at", "old_identifier", "old_value", "new_identifier", "new_value")
    )

    if moves:
        first = moves[0]
        start_id, start_name = first["old_identifier"], first["old_value"]
        if start_id is None and not start_name:
            # Moves out of triage are recorded without the old state: the card came in through intake.
            if IntakeIssue.objects.filter(issue_id=issue.id).exists():
                triage = next((s for s in states.values() if s.group == StateGroup.TRIAGE.value), None)
                start_id, start_name = (triage.id, triage.name) if triage else (None, "Triagem")
    else:
        start_id, start_name = issue.state_id, None

    # (state, entered_at) in chronological order.
    stops = [(_state_info(states, start_id, start_name), issue.created_at)]
    for move in moves:
        entered = max(move["created_at"], stops[-1][1])
        stops.append((_state_info(states, move["new_identifier"], move["new_value"]), entered))

    # History written asynchronously can lag behind the card: the card itself is the truth for "now".
    current = _state_info(states, issue.state_id, None)
    if issue.state_id and stops[-1][0]["state_id"] != current["state_id"]:
        stops.append((current, max(issue.state_changed_at or now, stops[-1][1])))

    segments = []
    for index, (state, entered) in enumerate(stops):
        left = stops[index + 1][1] if index + 1 < len(stops) else None
        if segments and segments[-1]["state_id"] == state["state_id"] and segments[-1]["ended_at"] == entered:
            segments[-1]["ended_at"] = left
            continue
        segments.append({**state, "started_at": entered, "ended_at": left})

    done = segments[-1]["group"] in TERMINAL_GROUPS
    done_at = segments[-1]["started_at"] if done else None
    end = done_at or now

    totals = {}
    for segment in segments:
        is_last = segment is segments[-1]
        if is_last and done:
            segment["seconds"] = None
            continue
        until = segment["ended_at"] or end
        segment["seconds"] = max(0, int((until - segment["started_at"]).total_seconds()))
        key = segment["state_id"] or segment["name"]
        if key not in totals:
            totals[key] = {k: segment[k] for k in ("state_id", "name", "color", "group")} | {"seconds": 0}
        totals[key]["seconds"] += segment["seconds"]

    # Drop moves that lasted under a second (double clicks) except the current state.
    segments = [s for s in segments if s["seconds"] is None or s["seconds"] > 0 or s is segments[-1]]

    last = segments[-1]
    return {
        "segments": [
            {
                **s,
                "started_at": s["started_at"].isoformat(),
                "ended_at": s["ended_at"].isoformat() if s["ended_at"] else None,
            }
            for s in segments
        ],
        "totals": sorted(totals.values(), key=lambda t: -t["seconds"]),
        "created_at": issue.created_at.isoformat(),
        "current": current,
        "current_since": last["started_at"].isoformat(),
        "is_done": done,
        "done_at": done_at.isoformat() if done_at else None,
        "lead_seconds": max(0, int((end - issue.created_at).total_seconds())),
    }
