# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.urls import path

from .views import DesligarUsuarioEndpoint, UsuarioEndpoint, UsuariosEndpoint

urlpatterns = [
    path("usuarios/", UsuariosEndpoint.as_view(), name="conjo-painel-usuarios"),
    path("usuarios/<uuid:pk>/", UsuarioEndpoint.as_view(), name="conjo-painel-usuario"),
    path("usuarios/<uuid:pk>/desligar/", DesligarUsuarioEndpoint.as_view(), name="conjo-painel-desligar"),
]
