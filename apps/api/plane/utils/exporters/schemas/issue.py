# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from collections import defaultdict
from typing import Any, Dict, List, Optional

from django.db.models import F, QuerySet

from plane.db.models import CycleIssue, FileAsset

from .base import (
    DateField,
    DateTimeField,
    ExportSchema,
    JSONField,
    ListField,
    NumberField,
    StringField,
)


def get_issue_attachments_dict(issues_queryset: QuerySet) -> Dict[str, List[str]]:
    """Get attachments dictionary for the given issues queryset.

    Args:
        issues_queryset: Queryset of Issue objects

    Returns:
        Dictionary mapping issue IDs to lists of attachment IDs
    """
    file_assets = FileAsset.objects.filter(
        issue_id__in=issues_queryset.values_list("id", flat=True),
        entity_type=FileAsset.EntityTypeContext.ISSUE_ATTACHMENT,
    ).annotate(work_item_id=F("issue_id"), asset_id=F("id"))

    attachment_dict = defaultdict(list)
    for asset in file_assets:
        attachment_dict[asset.work_item_id].append(asset.asset_id)

    return attachment_dict


def get_issue_last_cycles_dict(issues_queryset: QuerySet) -> Dict[str, Optional[CycleIssue]]:
    """Get the last cycle for each issue in the given queryset.

    Args:
        issues_queryset: Queryset of Issue objects

    Returns:
        Dictionary mapping issue IDs to their last CycleIssue object
    """
    # Fetch all cycle issues for the given issues, ordered by created_at descending
    # select_related is used to fetch cycle data in the same query
    cycle_issues = (
        CycleIssue.objects.filter(issue_id__in=issues_queryset.values_list("id", flat=True))
        .select_related("cycle")
        .order_by("issue_id", "-created_at")
    )

    # Keep only the last (most recent) cycle for each issue
    last_cycles_dict = {}
    for cycle_issue in cycle_issues:
        if cycle_issue.issue_id not in last_cycles_dict:
            last_cycles_dict[cycle_issue.issue_id] = cycle_issue

    return last_cycles_dict


class IssueExportSchema(ExportSchema):
    """Schema for exporting issue data in various formats."""

    @staticmethod
    def _get_created_by(obj) -> str:
        """Get the created by user for the given object."""
        try:
            if getattr(obj, "created_by", None):
                return f"{obj.created_by.first_name} {obj.created_by.last_name}"
        except Exception:
            pass
        return ""

    @staticmethod
    def _format_date(date_obj) -> str:
        """Format date object to string."""
        if date_obj and hasattr(date_obj, "strftime"):
            return date_obj.strftime("%a, %d %b %Y")
        return ""

    # Field definitions with display labels
    id = StringField(label="ID")
    project_identifier = StringField(source="project.identifier", label="Identificador do projeto")
    project_name = StringField(source="project.name", label="Projeto")
    project_id = StringField(source="project.id", label="ID do projeto")
    sequence_id = NumberField(source="sequence_id", label="Número sequencial")
    name = StringField(source="name", label="Nome")
    description = StringField(source="description_stripped", label="Descrição")
    priority = StringField(source="priority", label="Prioridade")
    start_date = DateField(source="start_date", label="Data de início")
    target_date = DateField(source="target_date", label="Data de entrega")
    state_name = StringField(label="Estado")
    created_at = DateTimeField(source="created_at", label="Criada em")
    updated_at = DateTimeField(source="updated_at", label="Atualizada em")
    completed_at = DateTimeField(source="completed_at", label="Concluída em")
    archived_at = DateTimeField(source="archived_at", label="Arquivada em")
    module_name = ListField(label="Módulo")
    created_by = StringField(label="Criada por")
    labels = ListField(label="Etiquetas")
    comments = JSONField(label="Comentários")
    estimate = StringField(label="Estimativa")
    link = ListField(label="Links")
    assignees = ListField(label="Responsáveis")
    subscribers_count = NumberField(label="Qtd. de inscritos")
    attachment_count = NumberField(label="Qtd. de anexos")
    attachment_links = ListField(label="Links dos anexos")
    cycle_name = StringField(label="Ciclo")
    cycle_start_date = DateField(label="Início do ciclo")
    cycle_end_date = DateField(label="Fim do ciclo")
    parent = StringField(label="Tarefa pai")
    relations = JSONField(label="Relações")

    def prepare_id(self, i):
        return f"{i.project.identifier}-{i.sequence_id}"

    def prepare_state_name(self, i):
        return i.state.name if i.state else None

    def prepare_module_name(self, i):
        return [m.module.name for m in i.issue_module.all()]

    def prepare_created_by(self, i):
        return self._get_created_by(i)

    def prepare_labels(self, i):
        return [label.name for label in i.labels.all()]

    def prepare_comments(self, i):
        return [
            {
                "comment": comment.comment_stripped,
                "created_at": self._format_date(comment.created_at),
                "created_by": self._get_created_by(comment),
            }
            for comment in i.issue_comments.all()
        ]

    def prepare_estimate(self, i):
        return i.estimate_point.value if i.estimate_point and i.estimate_point.value else ""

    def prepare_link(self, i):
        return [link.url for link in i.issue_link.all()]

    def prepare_assignees(self, i):
        return [f"{u.first_name} {u.last_name}" for u in i.assignees.all()]

    def prepare_subscribers_count(self, i):
        return i.issue_subscribers.count()

    def prepare_attachment_count(self, i):
        return len((self.context.get("attachments_dict") or {}).get(i.id, []))

    def prepare_attachment_links(self, i):
        return [
            f"/api/assets/v2/workspaces/{i.workspace.slug}/projects/{i.project_id}/issues/{i.id}/attachments/{asset}/"
            for asset in (self.context.get("attachments_dict") or {}).get(i.id, [])
        ]

    def prepare_cycle_name(self, i):
        cycles_dict = self.context.get("cycles_dict") or {}
        last_cycle = cycles_dict.get(i.id)
        return last_cycle.cycle.name if last_cycle else ""

    def prepare_cycle_start_date(self, i):
        cycles_dict = self.context.get("cycles_dict") or {}
        last_cycle = cycles_dict.get(i.id)
        if last_cycle and last_cycle.cycle.start_date:
            return self._format_date(last_cycle.cycle.start_date)
        return ""

    def prepare_cycle_end_date(self, i):
        cycles_dict = self.context.get("cycles_dict") or {}
        last_cycle = cycles_dict.get(i.id)
        if last_cycle and last_cycle.cycle.end_date:
            return self._format_date(last_cycle.cycle.end_date)
        return ""

    def prepare_parent(self, i):
        if not i.parent:
            return ""
        return f"{i.parent.project.identifier}-{i.parent.sequence_id}"

    def prepare_relations(self, i):
        # Should show reverse relation as well
        from plane.db.models.issue import IssueRelationChoices

        relations = {
            r.relation_type: f"{r.related_issue.project.identifier}-{r.related_issue.sequence_id}"
            for r in i.issue_relation.all()
        }
        reverse_relations = {}
        for relation in i.issue_related.all():
            reverse_relations[IssueRelationChoices._REVERSE_MAPPING[relation.relation_type]] = (
                f"{relation.issue.project.identifier}-{relation.issue.sequence_id}"
            )
        relations.update(reverse_relations)
        return relations

    @classmethod
    def get_context_data(cls, queryset: QuerySet) -> Dict[str, Any]:
        """Get context data for issue serialization."""
        return {
            "attachments_dict": get_issue_attachments_dict(queryset),
            "cycles_dict": get_issue_last_cycles_dict(queryset),
        }
