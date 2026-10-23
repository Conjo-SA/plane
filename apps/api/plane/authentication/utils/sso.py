# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# ConjoSA: quem entra pelo SSO (provedor OIDC, a Conta Conjo) nao tem senha no Plane.
# Se tivesse, continuaria entrando por e-mail e senha depois de desativado no
# diretorio, e desligar alguem numa acao so deixaria de funcionar. Por isso criar,
# trocar e redefinir senha, e entrar por senha ou por codigo, sao recusados para
# quem tem vinculo OIDC.

from plane.authentication.adapter.error import (
    AUTHENTICATION_ERROR_CODES,
    AuthenticationException,
)
from plane.db.models import Account

SSO_PROVIDER = "oidc"


def uses_sso(user):
    """True quando a conta ja entrou pelo SSO (tem vinculo com o provedor OIDC)."""
    return bool(user) and Account.objects.filter(user=user, provider=SSO_PROVIDER).exists()


def sso_password_exception(email=None):
    return AuthenticationException(
        error_code=AUTHENTICATION_ERROR_CODES["SSO_PASSWORD_DISABLED"],
        error_message="SSO_PASSWORD_DISABLED",
        payload={"email": email} if email else {},
    )
