# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Conjo: area gate (MAN-467).

A view declares ``conjo_area = "clients"`` (or docs, time, integrations, archives) and every method of it
goes through ``has_area_access`` before the handler runs, on top of the view's own role checks.
"""

from rest_framework.exceptions import PermissionDenied

from plane.utils.conjo_areas import denied_message, has_area_access


def check_area_access(view, request):
    area = getattr(view, "conjo_area", None)
    if not area:
        return
    # Fails closed: a view of an area without the workspace in the URL never opens.
    slug = view.kwargs.get("slug") if getattr(view, "kwargs", None) else None
    if not slug or not has_area_access(request.user, slug, area):
        raise PermissionDenied({"error": denied_message(area)})
