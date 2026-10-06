# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.urls import path

from plane.app.views.conjo_billing import (
    ClientContactDetailEndpoint,
    ClientContactsEndpoint,
    ClientContractDetailEndpoint,
    ClientContractsEndpoint,
    ClientDetailEndpoint,
    ClientLedgerAdjustEndpoint,
    ClientLedgerEndpoint,
    ClientLedgerExportEndpoint,
    ClientLedgerReverseEndpoint,
    ClientListEndpoint,
    ClientProjectsEndpoint,
    ClientTimelineEndpoint,
    ClientTimelineNoteDetailEndpoint,
    ClientTimelineNotesEndpoint,
    IssueTimeDetailEndpoint,
    IssueTimeEndpoint,
    IssueWorkKindEndpoint,
)

ISSUE = "workspaces/<str:slug>/projects/<uuid:project_id>/issues/<uuid:issue_id>"
CLIENT = "workspaces/<str:slug>/clients/<uuid:client_id>"

urlpatterns = [
    path(f"{ISSUE}/time/", IssueTimeEndpoint.as_view(), name="issue-time"),
    path(f"{ISSUE}/time/<uuid:pk>/", IssueTimeDetailEndpoint.as_view(), name="issue-time-detail"),
    path(f"{ISSUE}/work-kind/", IssueWorkKindEndpoint.as_view(), name="issue-work-kind"),
    path("workspaces/<str:slug>/clients/", ClientListEndpoint.as_view(), name="clients"),
    path(f"{CLIENT}/", ClientDetailEndpoint.as_view(), name="client-detail"),
    path(f"{CLIENT}/contacts/", ClientContactsEndpoint.as_view(), name="client-contacts"),
    path(f"{CLIENT}/contacts/<uuid:contact_id>/", ClientContactDetailEndpoint.as_view(), name="client-contact"),
    path(f"{CLIENT}/projects/", ClientProjectsEndpoint.as_view(), name="client-projects"),
    path(f"{CLIENT}/contracts/", ClientContractsEndpoint.as_view(), name="client-contracts"),
    path(f"{CLIENT}/contracts/<uuid:contract_id>/", ClientContractDetailEndpoint.as_view(), name="client-contract"),
    path(f"{CLIENT}/ledger/", ClientLedgerEndpoint.as_view(), name="client-ledger"),
    path(f"{CLIENT}/ledger/adjust/", ClientLedgerAdjustEndpoint.as_view(), name="client-ledger-adjust"),
    path(f"{CLIENT}/ledger/export/", ClientLedgerExportEndpoint.as_view(), name="client-ledger-export"),
    path(
        f"{CLIENT}/ledger/<uuid:entry_id>/reverse/", ClientLedgerReverseEndpoint.as_view(), name="client-ledger-reverse"
    ),
    path(f"{CLIENT}/timeline/", ClientTimelineEndpoint.as_view(), name="client-timeline"),
    path(f"{CLIENT}/timeline/notes/", ClientTimelineNotesEndpoint.as_view(), name="client-timeline-notes"),
    path(
        f"{CLIENT}/timeline/notes/<uuid:note_id>/",
        ClientTimelineNoteDetailEndpoint.as_view(),
        name="client-timeline-note",
    ),
]
