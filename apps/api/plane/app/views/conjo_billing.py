# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Conjo: time spent on work items, work kind, clients, hour packages and the client timeline."""

# Python imports
import csv
import datetime

# Django imports
from django.db import transaction
from django.db.models import Sum
from django.http import HttpResponse
from django.utils import timezone
from django.utils.text import slugify

# Third party imports
from rest_framework import status
from rest_framework.response import Response

# Module imports
from plane.app.permissions import ROLE, allow_permission
from plane.app.views.base import BaseAPIView
from plane.utils.realtime import publish_project_event
from plane.db.models import (
    Client,
    ClientContact,
    ClientContract,
    ClientLabel,
    ClientProject,
    ClientTimelineNote,
    HourLedgerEntry,
    IntakePortalBudget,
    Issue,
    IssueClient,
    IssueWorkKind,
    IssueWorkLog,
    Label,
    Project,
    ProjectMember,
    Workspace,
    WorkspaceMember,
)
from plane.utils import conjo_billing as billing
from plane.utils.uuid import is_valid_uuid
from plane.utils.conjo_timeline import TYPES, build_timeline
from plane.utils.conjo_state_timeline import build_state_timeline

NOT_FOUND = {"error": "Não encontrado."}


def _error(message, code=status.HTTP_400_BAD_REQUEST):
    return Response({"error": message}, status=code)


def _date(value, default=None):
    if not value:
        return default
    try:
        return datetime.date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _is_workspace_admin(user, slug):
    return WorkspaceMember.objects.filter(
        workspace__slug=slug, member=user, role=ROLE.ADMIN.value, is_active=True
    ).exists()


def _visible_project_ids(user, slug, project_ids):
    """Projects of ``project_ids`` whose work items ``user`` may see (admins see the whole workspace)."""
    project_ids = {str(p) for p in project_ids}
    if _is_workspace_admin(user, slug):
        return project_ids
    member_of = ProjectMember.objects.filter(
        project_id__in=project_ids, member=user, is_active=True, role__gte=ROLE.MEMBER.value
    ).values_list("project_id", flat=True)
    return {str(p) for p in member_of}


def _user(user):
    if user is None:
        return None
    return {
        "id": str(user.id),
        "display_name": user.display_name or user.first_name or user.email,
        "avatar_url": getattr(user, "avatar_url", "") or "",
    }


# --------------------------------------------------------------------------- #
# Time spent and work kind (work item)
# --------------------------------------------------------------------------- #


def _work_log(entry):
    return {
        "id": str(entry.id),
        "minutes": entry.minutes,
        "logged_on": entry.logged_on.isoformat(),
        "description": entry.description,
        "source": entry.source,
        "member": _user(entry.member),
        "created_at": entry.created_at.isoformat() if entry.created_at else None,
    }


def _issue_time_payload(issue):
    entries = IssueWorkLog.objects.filter(issue=issue).select_related("member")
    budget = IntakePortalBudget.objects.filter(issue_id=issue.id).first()
    client, via = billing.client_resolution(issue)
    debit = billing.open_debit(issue)
    return {
        "entries": [_work_log(entry) for entry in entries],
        "total_minutes": sum(entry.minutes for entry in entries),
        "kind": billing.work_kind(issue),
        "budget": (
            {
                "hours": str(budget.estimated_hours),
                "status": budget.status,
                "approved_by_email": budget.approved_by_email,
                "approved_at": budget.approved_at.isoformat() if budget.approved_at else None,
            }
            if budget
            else None
        ),
        "debited_hours": str(-debit.hours) if debit else None,
        "client": {"id": str(client.id), "name": client.name, "via": via} if client else None,
    }


WORK_LOG_DESCRIPTION_REQUIRED = "Descreva o que foi feito."


def _work_log_description(value):
    return str(value or "").strip()[:2000]


def _get_issue(slug, project_id, issue_id):
    return Issue.objects.filter(workspace__slug=slug, project_id=project_id, pk=issue_id).first()


class IssueTimeEndpoint(BaseAPIView):
    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST])
    def get(self, request, slug, project_id, issue_id):
        issue = _get_issue(slug, project_id, issue_id)
        if issue is None:
            return Response(NOT_FOUND, status=status.HTTP_404_NOT_FOUND)
        is_guest = ProjectMember.objects.filter(
            project_id=project_id, member=request.user, role=ROLE.GUEST.value, is_active=True
        ).exists()
        if is_guest:
            # Same rule as the work item itself; estimates and the client stay with the team.
            if not issue.project.guest_view_all_features and issue.created_by_id != request.user.id:
                return _error("Você não tem acesso a esta tarefa.", status.HTTP_403_FORBIDDEN)
            payload = _issue_time_payload(issue)
            payload.update(budget=None, debited_hours=None, client=None)
            return Response(payload)
        return Response(_issue_time_payload(issue))

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER])
    def post(self, request, slug, project_id, issue_id):
        issue = _get_issue(slug, project_id, issue_id)
        if issue is None:
            return Response(NOT_FOUND, status=status.HTTP_404_NOT_FOUND)
        minutes = billing.parse_duration(request.data.get("minutes") or request.data.get("duration"))
        if not minutes or minutes > 24 * 60:
            return _error("Informe a duração, por exemplo 1h30 ou 45min (até 24h por apontamento).")
        logged_on = _date(request.data.get("logged_on"), billing.today())
        if logged_on is None or logged_on > billing.today():
            return _error("Data inválida.")
        description = _work_log_description(request.data.get("description"))
        if not description:
            return _error(WORK_LOG_DESCRIPTION_REQUIRED)
        IssueWorkLog.objects.create(
            issue=issue,
            project_id=issue.project_id,
            member=request.user,
            minutes=minutes,
            logged_on=logged_on,
            description=description,
        )
        publish_project_event("issue.time", project_id, [issue.id], request.user.id, ["time"], workspace_slug=slug)
        return Response(_issue_time_payload(issue), status=status.HTTP_201_CREATED)


class IssueTimeDetailEndpoint(BaseAPIView):
    def _entry(self, request, slug, project_id, issue_id, pk):
        entry = IssueWorkLog.objects.filter(
            workspace__slug=slug, project_id=project_id, issue_id=issue_id, pk=pk
        ).first()
        if entry is None:
            return None, Response(NOT_FOUND, status=status.HTTP_404_NOT_FOUND)
        is_admin = ProjectMember.objects.filter(
            project_id=project_id, member=request.user, role=ROLE.ADMIN.value, is_active=True
        ).exists()
        if entry.member_id != request.user.id and not is_admin:
            return None, _error("Só quem apontou (ou um administrador) pode alterar.", status.HTTP_403_FORBIDDEN)
        return entry, None

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER])
    def patch(self, request, slug, project_id, issue_id, pk):
        entry, error = self._entry(request, slug, project_id, issue_id, pk)
        if error:
            return error
        if "minutes" in request.data or "duration" in request.data:
            minutes = billing.parse_duration(request.data.get("minutes") or request.data.get("duration"))
            if not minutes or minutes > 24 * 60:
                return _error("Duração inválida.")
            entry.minutes = minutes
        if "logged_on" in request.data:
            logged_on = _date(request.data.get("logged_on"))
            if logged_on is None or logged_on > billing.today():
                return _error("Data inválida.")
            entry.logged_on = logged_on
        if "description" in request.data:
            entry.description = _work_log_description(request.data.get("description"))
        # Manual entries need a description; old ones without it only save when the edit adds one.
        if entry.source == IssueWorkLog.SOURCE_MANUAL and not entry.description:
            return _error(WORK_LOG_DESCRIPTION_REQUIRED)
        entry.save()
        publish_project_event("issue.time", project_id, [issue_id], request.user.id, ["time"], workspace_slug=slug)
        return Response(_issue_time_payload(entry.issue))

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER])
    def delete(self, request, slug, project_id, issue_id, pk):
        entry, error = self._entry(request, slug, project_id, issue_id, pk)
        if error:
            return error
        issue = entry.issue
        entry.delete()
        publish_project_event("issue.time", project_id, [issue_id], request.user.id, ["time"], workspace_slug=slug)
        return Response(_issue_time_payload(issue))


class IssueWorkKindEndpoint(BaseAPIView):
    """Evolution, maintenance or internal. Changing it keeps the package statement consistent."""

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER])
    def put(self, request, slug, project_id, issue_id):
        issue = _get_issue(slug, project_id, issue_id)
        if issue is None:
            return Response(NOT_FOUND, status=status.HTTP_404_NOT_FOUND)
        kind = request.data.get("kind")
        if kind not in dict(IssueWorkKind.KIND_CHOICES):
            return _error("Tipo inválido.")
        current = billing.work_kind(issue)
        if kind == current:
            return Response(_issue_time_payload(issue))
        # Changing the kind of an item with an approved estimate debits or gives back client hours,
        # which is a statement operation: only administrators can do it (same as a manual reversal).
        if billing.kind_change_touches_statement(issue) and not _is_workspace_admin(request.user, slug):
            return _error(
                "Esta tarefa tem orçamento aprovado: só um administrador pode mudar o tipo, porque isso altera o "
                "saldo do cliente.",
                status.HTTP_403_FORBIDDEN,
            )
        billing.change_work_kind(issue, kind)
        publish_project_event(
            "issue.work_kind", project_id, [issue.id], request.user.id, ["work_kind"], workspace_slug=slug
        )
        return Response(_issue_time_payload(issue))


def _issue_client_payload(issue, user, slug):
    client, via = billing.client_resolution(issue)
    project_client = billing.client_for_project(issue.project_id)
    is_guest_or_out = not ProjectMember.objects.filter(
        project_id=issue.project_id, member=user, is_active=True, role__gte=ROLE.MEMBER.value
    ).exists()
    # Changing who an item with an approved estimate is for moves debited hours: an admin decision.
    moves_hours = (
        billing.open_debit(issue) is not None
        or IntakePortalBudget.objects.filter(issue_id=issue.id, status="APPROVED").exists()
    )
    return {
        "client": {"id": str(client.id), "name": client.name, "via": via} if client else None,
        "project_client": {"id": str(project_client.id), "name": project_client.name} if project_client else None,
        "can_change": not is_guest_or_out and (not moves_hours or _is_workspace_admin(user, slug)),
    }


class IssueStateTimelineEndpoint(BaseAPIView):
    """How long the work item stayed in each board column, until it was done."""

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST])
    def get(self, request, slug, project_id, issue_id):
        issue = _get_issue(slug, project_id, issue_id)
        if issue is None:
            return Response(NOT_FOUND, status=status.HTTP_404_NOT_FOUND)
        is_guest = ProjectMember.objects.filter(
            project_id=project_id, member=request.user, role=ROLE.GUEST.value, is_active=True
        ).exists()
        if is_guest and not issue.project.guest_view_all_features and issue.created_by_id != request.user.id:
            return _error("Você não tem acesso a esta tarefa.", status.HTTP_403_FORBIDDEN)
        return Response(build_state_timeline(issue))


class IssueClientEndpoint(BaseAPIView):
    """The client a work item is for (chosen on the item, or inherited from its project)."""

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST])
    def get(self, request, slug, project_id, issue_id):
        issue = _get_issue(slug, project_id, issue_id)
        if issue is None:
            return Response(NOT_FOUND, status=status.HTTP_404_NOT_FOUND)
        return Response(_issue_client_payload(issue, request.user, slug))

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER])
    def put(self, request, slug, project_id, issue_id):
        issue = _get_issue(slug, project_id, issue_id)
        if issue is None:
            return Response(NOT_FOUND, status=status.HTTP_404_NOT_FOUND)
        if not _issue_client_payload(issue, request.user, slug)["can_change"]:
            return _error(
                "Esta tarefa tem orçamento aprovado: só um administrador pode trocar o cliente, porque isso move "
                "as horas debitadas.",
                status.HTTP_403_FORBIDDEN,
            )
        client_id = request.data.get("client_id")
        client = None
        if client_id:
            client = _get_client(slug, client_id) if is_valid_uuid(str(client_id)) else None
            if client is None or not client.is_active:
                return _error("Cliente não encontrado.")
        billing.set_issue_client(issue, client)
        publish_project_event("issue.client", project_id, [issue.id], request.user.id, ["client"], workspace_slug=slug)
        return Response(_issue_client_payload(issue, request.user, slug))


class ClientOptionsEndpoint(BaseAPIView):
    """Active clients for the work item's client picker."""

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER], level="WORKSPACE")
    def get(self, request, slug):
        clients = Client.objects.filter(workspace__slug=slug, is_active=True).order_by("name")
        return Response({"clients": [{"id": str(c.id), "name": c.name} for c in clients]})


class ProjectClientSummaryEndpoint(BaseAPIView):
    """Clients chosen on the project's work items, for the chip on board and list cards."""

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST])
    def get(self, request, slug, project_id):
        project_client = billing.client_for_project(project_id)
        links = IssueClient.objects.filter(project_id=project_id, workspace__slug=slug).select_related("client")
        return Response(
            {
                "project_client": {"id": str(project_client.id), "name": project_client.name}
                if project_client
                else None,
                "issues": {str(link.issue_id): {"id": str(link.client_id), "name": link.client.name} for link in links},
            }
        )


# --------------------------------------------------------------------------- #
# Clients
# --------------------------------------------------------------------------- #


def _workspace(slug):
    return Workspace.objects.filter(slug=slug).first()


def _get_client(slug, client_id):
    return Client.objects.filter(workspace__slug=slug, pk=client_id).first()


def _contact(contact):
    return {
        "id": str(contact.id),
        "name": contact.name,
        "email": contact.email,
        "phone": contact.phone,
        "role": contact.role,
        "can_approve": contact.can_approve,
    }


def _contract(contract):
    return {
        "id": str(contract.id),
        "name": contract.name,
        "hours_per_month": str(contract.hours_per_month),
        "accumulation_months": contract.accumulation_months,
        "credit_day": contract.credit_day,
        "starts_on": contract.starts_on.isoformat(),
        "ends_on": contract.ends_on.isoformat() if contract.ends_on else None,
        "low_balance_percent": contract.low_balance_percent,
        "is_active": contract.is_active,
    }


def _client(client, detail=False):
    contract = billing.active_contract(client)
    if contract is not None:
        billing.refresh_contract(contract)
    data = {
        "id": str(client.id),
        "name": client.name,
        "legal_name": client.legal_name,
        "document": client.document,
        "is_active": client.is_active,
        "package": billing.package_summary(contract) if contract else None,
        "project_ids": [str(p) for p in client.client_projects.values_list("project_id", flat=True)],
        "labels": [
            {
                "id": str(link.label_id),
                "name": link.label.name,
                "color": link.label.color,
                "project_id": str(link.label.project_id),
                "project_identifier": link.label.project.identifier,
            }
            for link in client.client_labels.select_related("label__project").order_by("label__name")
        ],
    }
    if detail:
        month = billing.month_start(billing.today())
        project_ids = data["project_ids"]
        maintenance = (
            IssueWorkLog.objects.filter(
                issue__in=billing.client_issues(client),
                logged_on__gte=month,
                issue__work_kind__kind__in=[IssueWorkKind.MAINTENANCE, IssueWorkKind.INTERNAL],
            ).aggregate(total=Sum("minutes"))["total"]
            or 0
        )
        data.update(
            notes=client.notes,
            contacts=[_contact(c) for c in client.contacts.all()],
            contracts=[_contract(c) for c in client.contracts.all()],
            projects=[
                {"id": str(p.id), "identifier": p.identifier, "name": p.name}
                for p in Project.objects.filter(pk__in=project_ids)
            ],
            maintenance_minutes_this_month=maintenance,
            created_at=client.created_at.isoformat() if client.created_at else None,
        )
    return data


CLIENT_FIELDS = ("name", "legal_name", "document", "notes", "is_active")


class ClientListEndpoint(BaseAPIView):
    @allow_permission([ROLE.ADMIN, ROLE.MEMBER], level="WORKSPACE")
    def get(self, request, slug):
        clients = Client.objects.filter(workspace__slug=slug)
        return Response([_client(client) for client in clients])

    @allow_permission([ROLE.ADMIN], level="WORKSPACE")
    def post(self, request, slug):
        name = (request.data.get("name") or "").strip()
        if not name:
            return _error("Informe o nome do cliente.")
        client = Client.objects.create(
            workspace=_workspace(slug),
            name=name[:255],
            legal_name=(request.data.get("legal_name") or "").strip()[:255],
            document=(request.data.get("document") or "").strip()[:32],
            notes=(request.data.get("notes") or "").strip(),
        )
        return Response(_client(client, detail=True), status=status.HTTP_201_CREATED)


class ClientDetailEndpoint(BaseAPIView):
    @allow_permission([ROLE.ADMIN, ROLE.MEMBER], level="WORKSPACE")
    def get(self, request, slug, client_id):
        client = _get_client(slug, client_id)
        if client is None:
            return Response(NOT_FOUND, status=status.HTTP_404_NOT_FOUND)
        return Response(_client(client, detail=True))

    @allow_permission([ROLE.ADMIN], level="WORKSPACE")
    def patch(self, request, slug, client_id):
        client = _get_client(slug, client_id)
        if client is None:
            return Response(NOT_FOUND, status=status.HTTP_404_NOT_FOUND)
        for field in CLIENT_FIELDS:
            if field in request.data:
                value = request.data[field]
                setattr(client, field, bool(value) if field == "is_active" else (value or "").strip())
        if not client.name:
            return _error("Informe o nome do cliente.")
        client.save()
        return Response(_client(client, detail=True))

    @allow_permission([ROLE.ADMIN], level="WORKSPACE")
    def delete(self, request, slug, client_id):
        client = _get_client(slug, client_id)
        if client is None:
            return Response(NOT_FOUND, status=status.HTTP_404_NOT_FOUND)
        client.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


CONTACT_FIELDS = ("name", "email", "phone", "role", "can_approve")


def _apply_contact(contact, data):
    for field in CONTACT_FIELDS:
        if field in data:
            value = data[field]
            setattr(contact, field, bool(value) if field == "can_approve" else (value or "").strip())
    return contact


class ClientContactsEndpoint(BaseAPIView):
    @allow_permission([ROLE.ADMIN], level="WORKSPACE")
    def post(self, request, slug, client_id):
        client = _get_client(slug, client_id)
        if client is None:
            return Response(NOT_FOUND, status=status.HTTP_404_NOT_FOUND)
        contact = _apply_contact(ClientContact(client=client, workspace_id=client.workspace_id), request.data)
        if not contact.name:
            return _error("Informe o nome do contato.")
        contact.save()
        return Response(_contact(contact), status=status.HTTP_201_CREATED)


class ClientContactDetailEndpoint(BaseAPIView):
    @allow_permission([ROLE.ADMIN], level="WORKSPACE")
    def patch(self, request, slug, client_id, contact_id):
        contact = ClientContact.objects.filter(workspace__slug=slug, client_id=client_id, pk=contact_id).first()
        if contact is None:
            return Response(NOT_FOUND, status=status.HTTP_404_NOT_FOUND)
        _apply_contact(contact, request.data)
        if not contact.name:
            return _error("Informe o nome do contato.")
        contact.save()
        return Response(_contact(contact))

    @allow_permission([ROLE.ADMIN], level="WORKSPACE")
    def delete(self, request, slug, client_id, contact_id):
        ClientContact.objects.filter(workspace__slug=slug, client_id=client_id, pk=contact_id).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ClientLabelOptionsEndpoint(BaseAPIView):
    """Every label of the workspace's projects with the client it identifies (for the label picker)."""

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER], level="WORKSPACE")
    def get(self, request, slug):
        owners = {
            link.label_id: {"id": str(link.client_id), "name": link.client.name}
            for link in ClientLabel.objects.filter(workspace__slug=slug).select_related("client")
        }
        labels = (
            Label.objects.filter(
                workspace__slug=slug,
                project__isnull=False,
                project__archived_at__isnull=True,
                parent__isnull=True,
            )
            .select_related("project")
            .order_by("project__name", "name")
        )
        return Response(
            {
                "labels": [
                    {
                        "id": str(label.id),
                        "name": label.name,
                        "color": label.color,
                        "project_id": str(label.project_id),
                        "project_identifier": label.project.identifier,
                        "project_name": label.project.name,
                        "client": owners.get(label.id),
                    }
                    for label in labels
                ]
            }
        )


class ClientLabelsEndpoint(BaseAPIView):
    """Replace the labels that identify the client on boards shared by several clients."""

    @allow_permission([ROLE.ADMIN], level="WORKSPACE")
    def put(self, request, slug, client_id):
        client = _get_client(slug, client_id)
        if client is None:
            return Response(NOT_FOUND, status=status.HTTP_404_NOT_FOUND)
        error = set_client_labels(client, request.data.get("label_ids") or [])
        if error:
            return _error(error)
        return Response(_client(client, detail=True))


class ClientProjectsEndpoint(BaseAPIView):
    """Replace the projects covered by the client (a project belongs to one client)."""

    @allow_permission([ROLE.ADMIN], level="WORKSPACE")
    def put(self, request, slug, client_id):
        client = _get_client(slug, client_id)
        if client is None:
            return Response(NOT_FOUND, status=status.HTTP_404_NOT_FOUND)
        error = set_client_projects(client, request.data.get("project_ids") or [])
        if error:
            return _error(error)
        return Response(_client(client, detail=True))


def set_client_projects(client, raw_ids):
    """Replace the client's projects (same workspace; a project belongs to one client). Returns an error or None."""
    if not isinstance(raw_ids, list) or not all(is_valid_uuid(str(p)) for p in raw_ids):
        return "Lista de projetos inválida."
    projects = list(Project.objects.filter(workspace_id=client.workspace_id, pk__in=[str(p) for p in raw_ids]))
    taken = ClientProject.objects.filter(project__in=projects).exclude(client=client).select_related("client")
    if taken:
        names = ", ".join(f"{link.project.identifier} ({link.client.name})" for link in taken)
        return f"Projeto já ligado a outro cliente: {names}."
    with transaction.atomic():
        ClientProject.objects.filter(client=client).exclude(project__in=projects).delete()
        existing = set(ClientProject.objects.filter(client=client).values_list("project_id", flat=True))
        for project in projects:
            if project.id not in existing:
                ClientProject.objects.create(client=client, project=project, workspace_id=client.workspace_id)
    return None


def set_client_labels(client, raw_ids):
    """Replace the labels that identify the client on shared boards. Returns an error or None."""
    if not isinstance(raw_ids, list) or not all(is_valid_uuid(str(p)) for p in raw_ids):
        return "Lista de etiquetas inválida."
    labels = list(
        Label.objects.filter(workspace_id=client.workspace_id, pk__in=[str(p) for p in raw_ids]).select_related(
            "project"
        )
    )
    if len(labels) != len(set(str(p) for p in raw_ids)):
        return "Etiqueta não encontrada neste workspace."
    taken = ClientLabel.objects.filter(label__in=labels).exclude(client=client).select_related("client", "label")
    if taken:
        names = ", ".join(f"{link.label.name} ({link.client.name})" for link in taken)
        return f"Etiqueta já ligada a outro cliente: {names}."
    with transaction.atomic():
        ClientLabel.objects.filter(client=client).exclude(label__in=labels).delete()
        existing = set(ClientLabel.objects.filter(client=client).values_list("label_id", flat=True))
        for label in labels:
            if label.id not in existing:
                ClientLabel.objects.create(client=client, label=label, workspace_id=client.workspace_id)
                # Cards already tagged with it (the board's history) become the client's.
                billing.adopt_labelled_cards(client, label)
    return None


def create_contract(client, data):
    """New package for the client; it replaces the active one (the balance moves over). Returns (contract, error)."""
    contract = ClientContract(client=client, workspace_id=client.workspace_id)
    errors = _apply_contract(contract, data)
    if contract.hours_per_month is None:
        errors.append("Informe as horas por mês.")
    opening = None
    if data.get("opening_balance") not in (None, "", 0, "0"):
        opening = billing.parse_hours(data.get("opening_balance"))
        if opening is None:
            errors.append("Saldo inicial inválido.")
    if errors:
        return None, " ".join(errors)
    with transaction.atomic():
        contract.save()
        # One active package per client: the new one replaces the previous, and what is left of
        # the previous one moves over with its original expiry (nothing disappears silently).
        for previous in ClientContract.objects.filter(client=client, is_active=True).exclude(pk=contract.pk):
            billing.close_contract(previous, replaced_by=contract)
        billing.refresh_contract(contract)
        if opening:
            billing.adjust(contract, opening, "Saldo inicial ao cadastrar o contrato")
    return contract, None


def update_contract(contract, data):
    """Change an active package, or end it with ``is_active: false``. Returns (contract, error)."""
    if not contract.is_active:
        return None, "Contrato encerrado não pode ser alterado. Cadastre um novo contrato."
    errors = _apply_contract(contract, data)
    if errors:
        return None, " ".join(errors)
    with transaction.atomic():
        contract.save()
        if data.get("is_active") is False:
            # Ending a package writes off what is left (a replacement is a new contract instead).
            billing.close_contract(contract)
        else:
            billing.refresh_contract(contract)
    contract.refresh_from_db()
    return contract, None


def _apply_contract(contract, data):
    errors = []
    if "name" in data:
        contract.name = (data.get("name") or "").strip()[:255]
    if "hours_per_month" in data:
        hours = billing.parse_hours(data.get("hours_per_month"))
        if hours is None or hours > 744:
            errors.append("Horas por mês inválidas.")
        else:
            contract.hours_per_month = hours
    if "accumulation_months" in data:
        try:
            months = int(data.get("accumulation_months"))
        except (TypeError, ValueError):
            months = 0
        if not 1 <= months <= 24:
            errors.append("Meses de acúmulo devem ficar entre 1 e 24.")
        else:
            contract.accumulation_months = months
    if "credit_day" in data:
        try:
            day = int(data.get("credit_day"))
        except (TypeError, ValueError):
            day = 0
        if not 1 <= day <= 28:
            errors.append("O dia do crédito deve ficar entre 1 e 28.")
        else:
            contract.credit_day = day
    for field in ("starts_on", "ends_on"):
        if field in data:
            value = _date(data.get(field))
            if data.get(field) and value is None:
                errors.append("Data inválida.")
            setattr(contract, field, value)
    if "low_balance_percent" in data:
        try:
            contract.low_balance_percent = max(0, min(100, int(data.get("low_balance_percent"))))
        except (TypeError, ValueError):
            errors.append("Percentual de aviso inválido.")
    if not contract.name:
        errors.append("Informe o nome do contrato.")
    if not contract.starts_on:
        errors.append("Informe o início do contrato.")
    if contract.ends_on and contract.starts_on and contract.ends_on < contract.starts_on:
        errors.append("O fim do contrato é antes do início.")
    return errors


class ClientContractsEndpoint(BaseAPIView):
    @allow_permission([ROLE.ADMIN], level="WORKSPACE")
    def post(self, request, slug, client_id):
        client = _get_client(slug, client_id)
        if client is None:
            return Response(NOT_FOUND, status=status.HTTP_404_NOT_FOUND)
        contract, error = create_contract(client, request.data)
        if error:
            return _error(error)
        return Response(_contract(contract), status=status.HTTP_201_CREATED)


class ClientContractDetailEndpoint(BaseAPIView):
    @allow_permission([ROLE.ADMIN], level="WORKSPACE")
    def patch(self, request, slug, client_id, contract_id):
        contract = ClientContract.objects.filter(workspace__slug=slug, client_id=client_id, pk=contract_id).first()
        if contract is None:
            return Response(NOT_FOUND, status=status.HTTP_404_NOT_FOUND)
        contract, error = update_contract(contract, request.data)
        if error:
            return _error(error)
        return Response(_contract(contract))


# --------------------------------------------------------------------------- #
# Statement
# --------------------------------------------------------------------------- #


def _ledger_entry(entry, running, visible_projects=None):
    issue = entry.issue
    if issue is not None and visible_projects is not None and str(issue.project_id) not in visible_projects:
        issue = None
    return {
        "id": str(entry.id),
        "kind": entry.kind,
        "hours": str(entry.hours),
        "occurred_on": entry.occurred_on.isoformat(),
        "note": entry.note,
        "balance": str(running),
        "issue": (
            {
                "id": str(issue.id),
                "project_id": str(issue.project_id),
                "key": f"{issue.project.identifier}-{issue.sequence_id}",
                "name": issue.name,
            }
            if issue
            else None
        ),
        "period": entry.period.isoformat() if entry.period else None,
        "expires_on": entry.expires_on.isoformat() if entry.expires_on else None,
        "lots": [allocation.get("lot") for allocation in entry.allocations or []],
        "reversed": entry.kind == HourLedgerEntry.DEBIT and entry.reversals.exists(),
        "exported_at": entry.exported_at.isoformat() if entry.exported_at else None,
        "author": _user(entry.created_by),
    }


def _contract_for_client(slug, client_id, contract_id=None):
    contracts = ClientContract.objects.filter(workspace__slug=slug, client_id=client_id)
    if contract_id:
        return contracts.filter(pk=contract_id).first()
    client = _get_client(slug, client_id)
    return billing.active_contract(client) if client else None


class ClientLedgerEndpoint(BaseAPIView):
    @allow_permission([ROLE.ADMIN, ROLE.MEMBER], level="WORKSPACE")
    def get(self, request, slug, client_id):
        if _get_client(slug, client_id) is None:
            return Response(NOT_FOUND, status=status.HTTP_404_NOT_FOUND)
        contract = _contract_for_client(slug, client_id, request.query_params.get("contract"))
        if contract is None:
            return Response({"package": None, "entries": []})
        billing.refresh_contract(contract)
        rows = billing.statement(
            contract, _date(request.query_params.get("from")), _date(request.query_params.get("to"))
        )
        lot_period = {
            str(lot.id): lot.period.isoformat() if lot.period else None
            for lot in HourLedgerEntry.objects.filter(contract=contract, period__isnull=False)
        }
        client = contract.client
        visible = _visible_project_ids(request.user, slug, billing.client_project_ids(client))
        entries = []
        for entry, running in rows:
            data = _ledger_entry(entry, running, visible)
            data["lot_periods"] = [lot_period.get(lot) for lot in data["lots"] if lot_period.get(lot)]
            entries.append(data)
        return Response(
            {"package": billing.package_summary(contract), "contract": _contract(contract), "entries": entries}
        )


class ClientLedgerAdjustEndpoint(BaseAPIView):
    @allow_permission([ROLE.ADMIN], level="WORKSPACE")
    def post(self, request, slug, client_id):
        contract = _contract_for_client(slug, client_id, request.data.get("contract"))
        if contract is None:
            return _error("O cliente não tem contrato ativo.")
        hours = billing.parse_hours(request.data.get("hours"), allow_negative=True)
        note = (request.data.get("note") or "").strip()[:2000]
        if hours is None:
            return _error("Informe as horas do ajuste (positivas ou negativas, até 9999).")
        if not note:
            return _error("Ajustes exigem uma justificativa.")
        billing.refresh_contract(contract)
        try:
            billing.adjust(contract, hours, note)
        except ValueError:
            return _error(f"Saldo insuficiente: o pacote tem {billing.balance(contract)}h disponíveis.")
        return Response(billing.package_summary(contract), status=status.HTTP_201_CREATED)


class ClientLedgerReverseEndpoint(BaseAPIView):
    @allow_permission([ROLE.ADMIN], level="WORKSPACE")
    def post(self, request, slug, client_id, entry_id):
        debit = HourLedgerEntry.objects.filter(
            workspace__slug=slug, contract__client_id=client_id, pk=entry_id, kind=HourLedgerEntry.DEBIT
        ).first()
        if debit is None:
            return Response(NOT_FOUND, status=status.HTTP_404_NOT_FOUND)
        reversal = billing.reverse_debit(debit, note=(request.data.get("note") or "").strip()[:2000])
        if reversal is None:
            return _error("Este débito já foi estornado.")
        return Response(billing.package_summary(debit.contract))


def _csv_cell(value):
    """Text a spreadsheet will not run: titles come from the public form, so formulas are neutralized."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def _export_period(params):
    start = _date(params.get("from"), billing.month_start(billing.today()))
    end = _date(params.get("to"), billing.today())
    if start is None or end is None or end < start:
        return None, None
    return start, end


def _export_entries(client, start, end):
    return (
        HourLedgerEntry.objects.filter(
            contract__client=client,
            occurred_on__gte=start,
            occurred_on__lte=end,
            kind__in=[HourLedgerEntry.DEBIT, HourLedgerEntry.REVERSAL, HourLedgerEntry.EXCESS],
        )
        .select_related("issue__project", "contract")
        .order_by("occurred_on", "created_at")
    )


class ClientLedgerExportEndpoint(BaseAPIView):
    """CSV for the finance system: debits and excess hours of a period.

    GET downloads; POST marks the period's excess hours as sent to finance (a state change never
    rides on a GET, which a link or an image could trigger).
    """

    @allow_permission([ROLE.ADMIN], level="WORKSPACE")
    def post(self, request, slug, client_id):
        client = _get_client(slug, client_id)
        if client is None:
            return Response(NOT_FOUND, status=status.HTTP_404_NOT_FOUND)
        start, end = _export_period(request.data)
        if start is None:
            return _error("Período inválido.")
        marked = (
            _export_entries(client, start, end)
            .filter(kind=HourLedgerEntry.EXCESS, exported_at__isnull=True)
            .update(exported_at=timezone.now())
        )
        return Response({"marked": marked})

    @allow_permission([ROLE.ADMIN], level="WORKSPACE")
    def get(self, request, slug, client_id):
        client = _get_client(slug, client_id)
        if client is None:
            return Response(NOT_FOUND, status=status.HTTP_404_NOT_FOUND)
        start, end = _export_period(request.query_params)
        if start is None:
            return _error("Período inválido.")
        entries = (
            HourLedgerEntry.objects.filter(
                contract__client=client,
                occurred_on__gte=start,
                occurred_on__lte=end,
                kind__in=[HourLedgerEntry.DEBIT, HourLedgerEntry.REVERSAL, HourLedgerEntry.EXCESS],
            )
            .select_related("issue__project", "contract")
            .order_by("occurred_on", "created_at")
        )
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        filename = f"horas-{slugify(client.name) or 'cliente'}-{start}-{end}.csv"
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        response.write("﻿")
        writer = csv.writer(response, delimiter=";")
        writer.writerow(
            ["data", "cliente", "contrato", "movimento", "tarefa", "titulo", "horas", "aprovado_por", "observacao"]
        )
        labels = dict(HourLedgerEntry.KIND_CHOICES)
        for entry in entries:
            issue = entry.issue
            writer.writerow(
                [
                    _csv_cell(value)
                    for value in (
                        entry.occurred_on.strftime("%d/%m/%Y"),
                        client.name,
                        entry.contract.name,
                        labels.get(entry.kind, entry.kind),
                        f"{issue.project.identifier}-{issue.sequence_id}" if issue else "",
                        issue.name if issue else "",
                        str(entry.hours).replace(".", ","),
                        entry.approved_by_email,
                        entry.note,
                    )
                ]
            )
        return response


# --------------------------------------------------------------------------- #
# Timeline
# --------------------------------------------------------------------------- #


class ClientTimelineEndpoint(BaseAPIView):
    @allow_permission([ROLE.ADMIN, ROLE.MEMBER], level="WORKSPACE")
    def get(self, request, slug, client_id):
        client = _get_client(slug, client_id)
        if client is None:
            return Response(NOT_FOUND, status=status.HTTP_404_NOT_FOUND)
        contract = billing.active_contract(client)
        if contract is not None:
            billing.refresh_contract(contract)
        types = [t for t in (request.query_params.get("types") or "").split(",") if t in TYPES] or None
        try:
            limit = max(5, min(100, int(request.query_params.get("limit") or 40)))
        except ValueError:
            limit = 40
        visible = _visible_project_ids(request.user, slug, billing.client_project_ids(client))
        try:
            return Response(
                build_timeline(client, types, request.query_params.get("before"), limit, visible_project_ids=visible)
            )
        except ValueError:
            return _error("Cursor inválido.")


class ClientTimelineNotesEndpoint(BaseAPIView):
    @allow_permission([ROLE.ADMIN, ROLE.MEMBER], level="WORKSPACE")
    def post(self, request, slug, client_id):
        client = _get_client(slug, client_id)
        if client is None:
            return Response(NOT_FOUND, status=status.HTTP_404_NOT_FOUND)
        kind = request.data.get("kind") or ClientTimelineNote.NOTE
        body = (request.data.get("body") or "").strip()
        if kind not in dict(ClientTimelineNote.KIND_CHOICES):
            return _error("Tipo de registro inválido.")
        if not body:
            return _error("Descreva o contato.")
        occurred_at = request.data.get("occurred_at")
        try:
            when = datetime.datetime.fromisoformat(occurred_at) if occurred_at else timezone.now()
        except ValueError:
            return _error("Data inválida.")
        if timezone.is_naive(when):
            # A time typed without an offset is the team's local time.
            when = timezone.make_aware(when, billing.BILLING_TZ)
        valid_contacts = {str(c) for c in client.contacts.values_list("id", flat=True)}
        note = ClientTimelineNote.objects.create(
            client=client,
            workspace_id=client.workspace_id,
            kind=kind,
            occurred_at=when,
            body=body[:5000],
            contact_ids=[c for c in request.data.get("contact_ids") or [] if str(c) in valid_contacts],
        )
        return Response({"id": str(note.id)}, status=status.HTTP_201_CREATED)


class ClientTimelineNoteDetailEndpoint(BaseAPIView):
    @allow_permission([ROLE.ADMIN, ROLE.MEMBER], level="WORKSPACE")
    def delete(self, request, slug, client_id, note_id):
        note = ClientTimelineNote.objects.filter(workspace__slug=slug, client_id=client_id, pk=note_id).first()
        if note is None:
            return Response(NOT_FOUND, status=status.HTTP_404_NOT_FOUND)
        if note.created_by_id != request.user.id:
            if not _is_workspace_admin(request.user, slug):
                return _error("Só quem registrou (ou um administrador) pode apagar.", status.HTTP_403_FORBIDDEN)
        note.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
