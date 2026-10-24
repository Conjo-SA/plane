# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# ConjoSA: endpoints do painel de acessos (painel-acessos.conjosa.com.br) para desligar
# uma pessoa do Plane numa acao so. A API publica (/api/v1) so tira membro de projeto:
# nao tira do workspace, nao desativa o usuario, nao revoga token nem derruba sessao.
#
# Autenticacao: segredo proprio (CONJO_PAINEL_SEGREDO) no cabecalho Authorization,
# sem relacao com usuario do Plane. Sem o segredo configurado (ou curto demais), as
# rotas respondem 404 como se nao existissem.
#
# Desligar segue a desativacao que o proprio usuario faz em /users/me/ (sessoes
# apagadas, senha aleatoria, is_active=False e last_logout_time, que barra o login
# por qualquer provedor, inclusive o OIDC), mais o que so um admin faz: tirar dos
# workspaces e projetos, apagar convites e revogar os tokens de API.

import hmac
import uuid

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.http import Http404
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from plane.db.models import (
    Account,
    APIToken,
    ProjectMember,
    Session,
    User,
    WorkspaceMember,
    WorkspaceMemberInvite,
)
from plane.license.models import InstanceAdmin

SEGREDO_MINIMO = 32
BUSCA_MINIMA = 3
ADMIN = 20


def _segredo_confere(request):
    segredo = getattr(settings, "CONJO_PAINEL_SEGREDO", "") or ""
    if len(segredo) < SEGREDO_MINIMO:
        return False
    enviado = request.headers.get("Authorization", "")
    return hmac.compare_digest(enviado.encode(), f"Bearer {segredo}".encode())


class PainelBase(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = []

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if not _segredo_confere(request):
            raise Http404()


def _nome(user):
    nome = f"{user.first_name or ''} {user.last_name or ''}".strip()
    return nome or user.display_name or ""


def resumo(user):
    workspaces = WorkspaceMember.objects.filter(member=user, is_active=True).select_related("workspace")
    return {
        "id": str(user.id),
        "email": user.email,
        "nome": _nome(user),
        "apelido": user.display_name,
        "ativo": user.is_active,
        "desativado_em": user.last_logout_time.isoformat()
        if (not user.is_active and user.last_logout_time)
        else None,
        "ultimo_acesso": user.last_active.isoformat() if user.last_active else None,
        "bot": user.is_bot,
        "admin_instancia": user.is_superuser or InstanceAdmin.objects.filter(user=user).exists(),
        "workspaces": [{"slug": m.workspace.slug, "papel": m.role} for m in workspaces],
        "projetos": ProjectMember.objects.filter(member=user, is_active=True).count(),
        "tokens": list(APIToken.objects.filter(user=user, is_active=True).values_list("label", flat=True)),
        "sessoes": Session.objects.filter(user_id=str(user.id)).count(),
        "logins": sorted(set(Account.objects.filter(user=user).values_list("provider", flat=True))),
    }


class UsuariosEndpoint(PainelBase):
    def get(self, request):
        busca = (request.query_params.get("busca") or "").strip()
        if len(busca) < BUSCA_MINIMA:
            return Response({"erro": f"busca com pelo menos {BUSCA_MINIMA} letras"}, status=status.HTTP_400_BAD_REQUEST)
        usuarios = User.objects.filter(
            Q(email__icontains=busca)
            | Q(display_name__icontains=busca)
            | Q(first_name__icontains=busca)
            | Q(last_name__icontains=busca)
        ).order_by("email")[:20]
        return Response({"usuarios": [resumo(u) for u in usuarios]})


class UsuarioEndpoint(PainelBase):
    def get(self, request, pk):
        user = User.objects.filter(pk=pk).first()
        if not user:
            return Response({"erro": "usuario nao encontrado"}, status=status.HTTP_404_NOT_FOUND)
        return Response(resumo(user))


def _apagados(retorno):
    """delete() do Django devolve (total, por_modelo); o soft delete do Plane devolve so o total."""
    return retorno[0] if isinstance(retorno, tuple) else retorno


def _unico_admin(qs, campo_grupo, user):
    """Grupos (workspace ou projeto) em que `user` e o unico admin ativo e ha outros membros."""
    presos = []
    for m in qs.filter(member=user, is_active=True, role=ADMIN):
        grupo = getattr(m, f"{campo_grupo}_id")
        outros = qs.filter(**{f"{campo_grupo}_id": grupo}, is_active=True).exclude(member=user)
        if outros.exists() and not outros.filter(role=ADMIN).exists():
            presos.append(str(getattr(m, campo_grupo)))
    return presos


class DesligarUsuarioEndpoint(PainelBase):
    def post(self, request, pk):
        user = User.objects.filter(pk=pk).first()
        if not user:
            return Response({"erro": "usuario nao encontrado"}, status=status.HTTP_404_NOT_FOUND)
        if user.is_bot:
            return Response({"erro": "conta de bot: desligar a mao"}, status=status.HTTP_409_CONFLICT)
        if user.is_superuser or InstanceAdmin.objects.filter(user=user).exists():
            return Response(
                {"erro": "administrador da instancia: o painel nao desliga, fazer a mao"},
                status=status.HTTP_409_CONFLICT,
            )
        presos = _unico_admin(WorkspaceMember.objects, "workspace", user) + _unico_admin(
            ProjectMember.objects, "project", user
        )
        if presos:
            return Response(
                {"erro": "unico admin de: " + ", ".join(presos) + " (promover outra pessoa antes)"},
                status=status.HTTP_409_CONFLICT,
            )

        with transaction.atomic():
            user = User.objects.select_for_update().get(pk=user.pk)
            estava_ativo = user.is_active
            projetos = ProjectMember.objects.filter(member=user, is_active=True).update(is_active=False)
            workspaces = WorkspaceMember.objects.filter(member=user, is_active=True).update(is_active=False)
            convites = _apagados(WorkspaceMemberInvite.objects.filter(email=user.email).delete())
            tokens = list(APIToken.objects.filter(user=user, is_active=True).values_list("label", flat=True))
            APIToken.objects.filter(user=user, is_active=True).update(is_active=False)
            sessoes = _apagados(Session.objects.filter(user_id=str(user.id)).delete())

            user.is_password_autoset = True
            user.set_password(uuid.uuid4().hex)
            user.is_active = False
            if estava_ativo or not user.last_logout_time:
                user.last_logout_time = timezone.now()
            user.token_updated_at = timezone.now()
            user.save()

        feito = [
            "usuario desativado" if estava_ativo else "usuario ja estava desativado",
            "senha trocada por uma aleatoria",
            f"{workspaces} workspace(s) e {projetos} projeto(s) deixados",
            f"{sessoes} sessao(oes) apagada(s)",
            f"{len(tokens)} token(s) de API revogado(s)" + (f": {', '.join(tokens)}" if tokens else ""),
            f"{convites} convite(s) apagado(s)",
        ]
        return Response({"feito": feito, "usuario": resumo(user)})
