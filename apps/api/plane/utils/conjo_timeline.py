# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Client timeline: one chronological feed built from what already exists in Tasks.

Sources: notes (meetings, calls, e-mails), the hour statement, requests from the public form,
estimates (sent, approved, rejected), finished work items and merged pull requests of the client's
projects. Nothing is copied: each request reads the sources and merges them.
"""

# Python imports
import datetime

# Django imports
from django.db.models import Sum
from django.utils import timezone

TYPE_REQUESTS = "requests"
TYPE_HOURS = "hours"
TYPE_CONTACTS = "contacts"
TYPE_DELIVERIES = "deliveries"
TYPES = (TYPE_REQUESTS, TYPE_HOURS, TYPE_CONTACTS, TYPE_DELIVERIES)


def _aware(value):
    from plane.utils.conjo_billing import BILLING_TZ

    if isinstance(value, datetime.datetime):
        return value if timezone.is_aware(value) else timezone.make_aware(value, BILLING_TZ)
    # Dates (statement entries) have no time: they sit at noon of their day in the business calendar,
    # so they group under the right day; the page shows them without a time.
    return timezone.make_aware(datetime.datetime.combine(value, datetime.time(12, 0)), BILLING_TZ)


def _ident(issue):
    return f"{issue.project.identifier}-{issue.sequence_id}"


def _issue_ref(issue):
    return {"id": str(issue.id), "project_id": str(issue.project_id), "key": _ident(issue), "name": issue.name}


def build_timeline(client, types=None, before=None, limit=40, visible_project_ids=None):
    """Newest first. ``types`` filters (see TYPES); ``before`` is an ISO datetime cursor.

    ``visible_project_ids`` limits work items, requests and pull requests to projects the reader can
    see (``None`` means all of the client's projects).
    """
    from plane.db.models import (
        ClientContact,
        HourLedgerEntry,
        IntakeIssue,
        IntakePortalBudget,
        IssueDevelopmentLink,
        IssueWorkKind,
        IssueWorkLog,
    )
    from plane.db.models.intake import SourceType

    wanted = set(types or TYPES)
    cursor = datetime.datetime.fromisoformat(before) if before else None
    if cursor is not None and timezone.is_naive(cursor):
        cursor = _aware(cursor)
    from plane.utils.conjo_billing import client_issues, client_project_ids

    # The client's work items: by label on shared boards, by project otherwise.
    project_ids = [p for p in client_project_ids(client)]
    if visible_project_ids is not None:
        project_ids = [p for p in project_ids if str(p) in visible_project_ids]
    visible = {str(p) for p in project_ids}
    issues = client_issues(client).filter(project_id__in=project_ids)
    events = []

    def add(at, kind, data):
        at = _aware(at)
        if cursor is None or at < cursor:
            events.append({"at": at, "type": kind, **data})

    if TYPE_CONTACTS in wanted:
        contacts = {str(c.id): c.name for c in ClientContact.objects.filter(client=client)}
        for note in client.timeline_notes.select_related("created_by").order_by("-occurred_at")[: limit * 2]:
            author = note.created_by
            add(
                note.occurred_at,
                "note",
                {
                    "id": str(note.id),
                    "kind": note.kind,
                    "body": note.body,
                    "contacts": [contacts[c] for c in note.contact_ids if c in contacts],
                    "author": (author.display_name or author.first_name) if author else "",
                },
            )

    if TYPE_HOURS in wanted:
        entries = (
            HourLedgerEntry.objects.filter(contract__client=client)
            .select_related("issue__project")
            .order_by("-occurred_on", "-created_at")[: limit * 2]
        )
        for entry in entries:
            add(
                entry.occurred_on,
                "ledger",
                {
                    "id": str(entry.id),
                    "kind": entry.kind,
                    "hours": str(entry.hours),
                    "note": entry.note,
                    "expires_on": entry.expires_on.isoformat() if entry.expires_on else None,
                    "issue": _issue_ref(entry.issue)
                    if entry.issue and str(entry.issue.project_id) in visible
                    else None,
                },
            )

    if project_ids and TYPE_REQUESTS in wanted:
        requests = (
            IntakeIssue.objects.filter(issue__in=issues, source=SourceType.PORTAL)
            .select_related("issue__project")
            .order_by("-created_at")[: limit * 2]
        )
        for request in requests:
            add(
                request.created_at,
                "request",
                {
                    "issue": _issue_ref(request.issue),
                    "requester": (request.extra or {}).get("requester_name") or request.source_email or "",
                },
            )
        for budget in IntakePortalBudget.objects.filter(issue__in=issues).select_related("issue__project"):
            base = {"issue": _issue_ref(budget.issue), "hours": str(budget.estimated_hours)}
            if budget.requested_at:
                add(budget.requested_at, "estimate_sent", base)
            if budget.approved_at:
                add(budget.approved_at, "estimate_approved", {**base, "by": budget.approved_by_email or ""})
            if budget.rejected_at:
                add(
                    budget.rejected_at,
                    "estimate_rejected",
                    {**base, "by": budget.rejected_by_email or "", "reason": budget.rejection_reason},
                )

    if project_ids and TYPE_DELIVERIES in wanted:
        done = (
            issues.filter(completed_at__isnull=False).select_related("project").order_by("-completed_at")[: limit * 2]
        )
        done = list(done)
        minutes = dict(
            IssueWorkLog.objects.filter(issue__in=done)
            .values_list("issue_id")
            .annotate(total=Sum("minutes"))
            .values_list("issue_id", "total")
        )
        kinds = dict(IssueWorkKind.objects.filter(issue__in=done).values_list("issue_id", "kind"))
        # approved estimates add up (a ticket can have several)
        budgets = dict(
            IntakePortalBudget.objects.filter(issue__in=done, status="APPROVED")
            .values_list("issue_id")
            .annotate(total=Sum("estimated_hours"))
            .values_list("issue_id", "total")
        )
        for issue in done:
            add(
                issue.completed_at,
                "delivered",
                {
                    "issue": _issue_ref(issue),
                    "kind": kinds.get(issue.id),
                    "minutes": int(minutes.get(issue.id) or 0),
                    "estimated_hours": str(budgets[issue.id]) if issue.id in budgets else None,
                },
            )
        merged = (
            IssueDevelopmentLink.objects.filter(
                issue__in=issues,
                kind=IssueDevelopmentLink.KIND_PULL_REQUEST,
                state="merged",
                event_at__isnull=False,
            )
            .select_related("issue__project")
            .order_by("-event_at")[: limit * 2]
        )
        for link in merged:
            add(
                link.event_at,
                "pr_merged",
                {
                    "issue": _issue_ref(link.issue),
                    "number": link.external_id,
                    "title": link.title,
                    "url": link.url,
                    "repository": link.repository,
                    "author": link.author_login,
                },
            )

    events.sort(key=lambda event: event["at"], reverse=True)
    page = events[:limit]
    for event in page:
        event["at"] = event["at"].isoformat()
    return {"events": page, "next_before": page[-1]["at"] if len(events) > limit else None}
