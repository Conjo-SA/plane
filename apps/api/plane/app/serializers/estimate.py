# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Module imports
from .base import BaseSerializer

from plane.db.models import Estimate, EstimatePoint

from rest_framework import serializers


class EstimateSerializer(BaseSerializer):
    class Meta:
        model = Estimate
        fields = "__all__"
        read_only_fields = ["workspace", "project"]


class EstimatePointSerializer(BaseSerializer):
    def validate(self, data):
        if not data:
            raise serializers.ValidationError("Os pontos de estimativa são obrigatórios")
        value = data.get("value")
        if value and len(value) > 20:
            raise serializers.ValidationError("O valor não pode ter mais de 20 caracteres")
        return data

    class Meta:
        model = EstimatePoint
        fields = "__all__"
        read_only_fields = ["estimate", "workspace", "project"]


class EstimateReadSerializer(BaseSerializer):
    points = EstimatePointSerializer(read_only=True, many=True)

    class Meta:
        model = Estimate
        fields = "__all__"
        read_only_fields = ["points", "name", "description"]


class WorkspaceEstimateSerializer(BaseSerializer):
    points = EstimatePointSerializer(read_only=True, many=True)

    class Meta:
        model = Estimate
        fields = "__all__"
        read_only_fields = ["points", "name", "description"]
