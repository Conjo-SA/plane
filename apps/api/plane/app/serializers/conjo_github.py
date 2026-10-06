# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Third party imports
from rest_framework import serializers

# Module imports
from plane.db.models import IssueDevelopmentLink, ProjectGitHubSettings

from .base import BaseSerializer


class IssueDevelopmentLinkSerializer(BaseSerializer):
    class Meta:
        model = IssueDevelopmentLink
        fields = [
            "id",
            "kind",
            "repository",
            "external_id",
            "title",
            "url",
            "state",
            "author_login",
            "author_name",
            "author_avatar_url",
            "event_at",
            "metadata",
        ]
        read_only_fields = fields


class ProjectGitHubSettingsSerializer(BaseSerializer):
    class Meta:
        model = ProjectGitHubSettings
        fields = ["id", "project", "smart_commits", "pr_opened_state", "pr_merged_state"]
        read_only_fields = ["id", "project"]

    def validate(self, attrs):
        project = self.instance.project if self.instance else None
        for field in ("pr_opened_state", "pr_merged_state"):
            state = attrs.get(field)
            if state is not None and project is not None and state.project_id != project.id:
                raise serializers.ValidationError({field: "Estado de outro projeto."})
        return attrs
