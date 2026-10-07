# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Marca Conjo SA nos templates (e-mails).

Registrado como "builtin" em TEMPLATES, então os templates usam
``{% brand_logo_url "white" %}`` sem precisar de ``{% load %}``.
O logo é servido pela própria instância (apps/web/public/conjo).
"""

from django import template
from django.conf import settings

register = template.Library()

_VARIANTS = {"black", "white"}


@register.simple_tag
def brand_logo_url(variant="black"):
    """URL absoluta do logo Conjo: "black" para fundo claro, "white" para fundo escuro."""
    variant = variant if variant in _VARIANTS else "black"
    base = (getattr(settings, "TASKS_PUBLIC_URL", "") or "").rstrip("/")
    return f"{base}/conjo/conjo-logo-{variant}.png"
