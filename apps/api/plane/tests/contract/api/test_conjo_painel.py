# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""ConjoSA: endpoints do painel de acessos (plane/conjo_painel)."""

from uuid import uuid4

import pytest
from rest_framework import status

from plane.db.models import (
    APIToken,
    Project,
    ProjectMember,
    Session,
    User,
    Workspace,
    WorkspaceMember,
    WorkspaceMemberInvite,
)
from plane.license.models import Instance, InstanceAdmin

SEGREDO = "s" * 40
BASE = "/api/conjo-painel/usuarios/"


def _usuario(email, **extra):
    u = User.objects.create(email=email, username=uuid4().hex, first_name="Fulano", last_name="Tal", **extra)
    u.set_password("senha-antiga-123")
    u.save()
    return u


@pytest.fixture
def painel(api_client, settings):
    settings.CONJO_PAINEL_SEGREDO = SEGREDO
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {SEGREDO}")
    return api_client


@pytest.fixture
def cenario(db):
    dono = _usuario("dono@conjosa.com.br")
    alvo = _usuario("ryan@gmail.com")
    ws = Workspace.objects.create(name="Conjo", slug=f"conjo-{uuid4().hex[:6]}", owner=dono)
    WorkspaceMember.objects.create(workspace=ws, member=dono, role=20)
    WorkspaceMember.objects.create(workspace=ws, member=alvo, role=20)
    proj = Project.objects.create(name="Manutencao", identifier=f"M{uuid4().hex[:4].upper()}", workspace=ws)
    ProjectMember.objects.create(project=proj, workspace=ws, member=dono, role=20)
    ProjectMember.objects.create(project=proj, workspace=ws, member=alvo, role=20)
    APIToken.objects.create(user=alvo, label="conjochat", token=f"plane_api_{uuid4().hex}")
    Session.objects.create(session_key=uuid4().hex, session_data="x", expire_date="2099-01-01T00:00Z",
                           user_id=str(alvo.id))
    WorkspaceMemberInvite.objects.create(workspace=ws, email=alvo.email, token=uuid4().hex, role=15)
    return {"dono": dono, "alvo": alvo, "ws": ws, "proj": proj}


@pytest.mark.contract
@pytest.mark.django_db
class TestConjoPainel:
    def test_sem_segredo_configurado_nao_existe(self, api_client, settings, cenario):
        settings.CONJO_PAINEL_SEGREDO = ""
        api_client.credentials(HTTP_AUTHORIZATION="Bearer ")
        r = api_client.get(BASE, {"busca": "ryan"})
        assert r.status_code == status.HTTP_404_NOT_FOUND

    def test_segredo_errado_nao_existe(self, api_client, settings, cenario):
        settings.CONJO_PAINEL_SEGREDO = SEGREDO
        api_client.credentials(HTTP_AUTHORIZATION="Bearer " + "x" * 40)
        assert api_client.get(BASE, {"busca": "ryan"}).status_code == status.HTTP_404_NOT_FOUND
        r = api_client.post(f"{BASE}{cenario['alvo'].id}/desligar/")
        assert r.status_code == status.HTTP_404_NOT_FOUND
        cenario["alvo"].refresh_from_db()
        assert cenario["alvo"].is_active

    def test_segredo_curto_desliga_as_rotas(self, api_client, settings, cenario):
        settings.CONJO_PAINEL_SEGREDO = "curto"
        api_client.credentials(HTTP_AUTHORIZATION="Bearer curto")
        assert api_client.get(BASE, {"busca": "ryan"}).status_code == status.HTTP_404_NOT_FOUND

    def test_busca(self, painel, cenario):
        assert painel.get(BASE, {"busca": "ry"}).status_code == status.HTTP_400_BAD_REQUEST
        r = painel.get(BASE, {"busca": "RYAN"})
        assert r.status_code == status.HTTP_200_OK
        (u,) = r.json()["usuarios"]
        assert u["email"] == "ryan@gmail.com"
        assert u["ativo"] is True
        assert u["tokens"] == ["conjochat"]
        assert u["sessoes"] == 1
        assert u["projetos"] == 1
        assert u["workspaces"][0]["papel"] == 20

    def test_desligar(self, painel, cenario):
        alvo = cenario["alvo"]
        r = painel.post(f"{BASE}{alvo.id}/desligar/")
        assert r.status_code == status.HTTP_200_OK, r.content
        alvo.refresh_from_db()
        assert alvo.is_active is False
        assert alvo.last_logout_time is not None
        assert not alvo.check_password("senha-antiga-123")
        assert not WorkspaceMember.objects.filter(member=alvo, is_active=True).exists()
        assert not ProjectMember.objects.filter(member=alvo, is_active=True).exists()
        assert not APIToken.objects.filter(user=alvo, is_active=True).exists()
        assert not Session.objects.filter(user_id=str(alvo.id)).exists()
        assert not WorkspaceMemberInvite.objects.filter(email=alvo.email).exists()
        assert any("conjochat" in linha for linha in r.json()["feito"])
        # o dono nao foi tocado
        assert WorkspaceMember.objects.filter(member=cenario["dono"], is_active=True).exists()

    def test_token_revogado_nao_entra_na_api(self, painel, api_client, cenario):
        token = APIToken.objects.get(user=cenario["alvo"]).token
        painel.post(f"{BASE}{cenario['alvo'].id}/desligar/")
        api_client.credentials(HTTP_X_API_KEY=token)
        # sem WWW-Authenticate o DRF devolve 403 (ver test_authentication.py)
        assert api_client.get("/api/v1/users/me/").status_code in (status.HTTP_401_UNAUTHORIZED,
                                                                   status.HTTP_403_FORBIDDEN)

    def test_desligar_de_novo_e_idempotente(self, painel, cenario):
        alvo = cenario["alvo"]
        painel.post(f"{BASE}{alvo.id}/desligar/")
        alvo.refresh_from_db()
        primeira = alvo.last_logout_time
        r = painel.post(f"{BASE}{alvo.id}/desligar/")
        assert r.status_code == status.HTTP_200_OK
        assert r.json()["feito"][0] == "usuario ja estava desativado"
        alvo.refresh_from_db()
        assert alvo.last_logout_time == primeira

    def test_unico_admin_nao_e_desligado(self, painel, cenario):
        WorkspaceMember.objects.filter(member=cenario["dono"]).update(role=15)
        r = painel.post(f"{BASE}{cenario['alvo'].id}/desligar/")
        assert r.status_code == status.HTTP_409_CONFLICT
        assert "unico admin" in r.json()["erro"]
        cenario["alvo"].refresh_from_db()
        assert cenario["alvo"].is_active

    def test_admin_da_instancia_nao_e_desligado(self, painel, cenario):
        instancia = Instance.objects.create(instance_name="teste", instance_id=uuid4().hex, current_version="1",
                                            last_checked_at="2026-01-01T00:00Z")
        InstanceAdmin.objects.create(user=cenario["alvo"], instance=instancia, role=20)
        r = painel.post(f"{BASE}{cenario['alvo'].id}/desligar/")
        assert r.status_code == status.HTTP_409_CONFLICT
        cenario["alvo"].refresh_from_db()
        assert cenario["alvo"].is_active

    def test_get_nao_desliga(self, painel, cenario):
        assert painel.get(f"{BASE}{cenario['alvo'].id}/desligar/").status_code == status.HTTP_405_METHOD_NOT_ALLOWED
        cenario["alvo"].refresh_from_db()
        assert cenario["alvo"].is_active
