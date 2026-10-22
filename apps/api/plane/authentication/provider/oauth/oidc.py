# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# ConjoSA: provedor OIDC generico. Usado para o login pelo conjo-mail (Stalwart,
# mail.interno.conjosa.com.br), mas serve para qualquer provedor OIDC com discovery.
# Os enderecos (authorize, token, userinfo) saem do
# <OIDC_ISSUER>/.well-known/openid-configuration; o login usa PKCE (S256).

import base64
import hashlib
import logging
import os
import secrets
from datetime import datetime, timedelta
from urllib.parse import urlencode, urlparse

import pytz
import requests

# Module imports
from plane.authentication.adapter.oauth import OauthAdapter
from plane.license.utils.instance_value import get_configuration_value
from plane.authentication.adapter.error import (
    AUTHENTICATION_ERROR_CODES,
    AuthenticationException,
)

# Chave da sessao onde fica o code_verifier do PKCE entre o inicio e o callback.
PKCE_SESSION_KEY = "oidc_code_verifier"

# O discovery roda antes do Adapter.__init__, que e quem cria self.logger.
logger = logging.getLogger("plane.authentication")


class OIDCOAuthProvider(OauthAdapter):
    provider = "oidc"

    def __init__(self, request, code=None, state=None, callback=None):
        (OIDC_ISSUER, OIDC_CLIENT_ID, OIDC_CLIENT_SECRET, OIDC_SCOPES) = get_configuration_value(
            [
                {
                    "key": "OIDC_ISSUER",
                    "default": os.environ.get("OIDC_ISSUER"),
                },
                {
                    "key": "OIDC_CLIENT_ID",
                    "default": os.environ.get("OIDC_CLIENT_ID"),
                },
                {
                    "key": "OIDC_CLIENT_SECRET",
                    "default": os.environ.get("OIDC_CLIENT_SECRET"),
                },
                {
                    "key": "OIDC_SCOPES",
                    "default": os.environ.get("OIDC_SCOPES", "openid email profile"),
                },
            ]
        )

        if not (OIDC_ISSUER and OIDC_CLIENT_ID and OIDC_CLIENT_SECRET):
            raise AuthenticationException(
                error_code=AUTHENTICATION_ERROR_CODES["OIDC_NOT_CONFIGURED"],
                error_message="OIDC_NOT_CONFIGURED",
            )

        parsed = urlparse(OIDC_ISSUER)
        if parsed.scheme != "https" or not parsed.netloc:
            raise AuthenticationException(
                error_code=AUTHENTICATION_ERROR_CODES["OIDC_NOT_CONFIGURED"],
                error_message="OIDC_NOT_CONFIGURED",  # avoid leaking details to query params
            )
        issuer = OIDC_ISSUER.rstrip("/")
        metadata = self.__discover(issuer)

        self.scope = OIDC_SCOPES or "openid"
        redirect_uri = f"{'https' if request.is_secure() else 'http'}://{request.get_host()}/auth/oidc/callback/"

        url_params = {
            "client_id": OIDC_CLIENT_ID,
            "scope": self.scope,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "state": state,
        }
        if code is None:
            # Inicio do login: gera o code_verifier e guarda na sessao para o callback.
            code_verifier = secrets.token_urlsafe(64)
            request.session[PKCE_SESSION_KEY] = code_verifier
            digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
            url_params["code_challenge"] = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
            url_params["code_challenge_method"] = "S256"
        auth_url = f"{metadata['authorization_endpoint']}?{urlencode(url_params)}"

        super().__init__(
            request,
            self.provider,
            OIDC_CLIENT_ID,
            self.scope,
            redirect_uri,
            auth_url,
            metadata["token_endpoint"],
            metadata["userinfo_endpoint"],
            OIDC_CLIENT_SECRET,
            code,
            callback=callback,
        )

    def __discover(self, issuer):
        error = AuthenticationException(
            error_code=AUTHENTICATION_ERROR_CODES["OIDC_OAUTH_PROVIDER_ERROR"],
            error_message="OIDC_OAUTH_PROVIDER_ERROR",
        )
        try:
            response = requests.get(f"{issuer}/.well-known/openid-configuration", timeout=10)
            response.raise_for_status()
            metadata = response.json()
        except (requests.RequestException, ValueError):
            logger.warning("Error fetching the OIDC discovery document")
            raise error
        # O documento tem que ser do proprio issuer configurado (OpenID Discovery 1.0, 4.3).
        if str(metadata.get("issuer", "")).rstrip("/") != issuer:
            logger.warning("OIDC discovery issuer does not match the configured issuer")
            raise error
        endpoints = ("authorization_endpoint", "token_endpoint", "userinfo_endpoint")
        if not all(str(metadata.get(key, "")).startswith("https://") for key in endpoints):
            logger.warning("OIDC discovery document is missing https endpoints")
            raise error
        return metadata

    def set_token_data(self):
        code_verifier = self.request.session.pop(PKCE_SESSION_KEY, None)
        if not code_verifier:
            raise AuthenticationException(
                error_code=AUTHENTICATION_ERROR_CODES["OIDC_OAUTH_PROVIDER_ERROR"],
                error_message="OIDC_OAUTH_PROVIDER_ERROR",
            )
        data = {
            "code": self.code,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "redirect_uri": self.redirect_uri,
            "grant_type": "authorization_code",
            "code_verifier": code_verifier,
        }
        headers = {"Accept": "application/json"}
        token_response = self.get_user_token(data=data, headers=headers)
        super().set_token_data(
            {
                "access_token": token_response.get("access_token"),
                "refresh_token": token_response.get("refresh_token", None),
                "access_token_expired_at": (
                    datetime.now(tz=pytz.utc) + timedelta(seconds=token_response.get("expires_in"))
                    if token_response.get("expires_in")
                    else None
                ),
                "refresh_token_expired_at": None,
                "id_token": token_response.get("id_token", ""),
            }
        )

    def set_user_data(self):
        user_info_response = self.get_user_response()

        subject = user_info_response.get("sub")
        email = user_info_response.get("email")
        if not subject or not email:
            raise AuthenticationException(
                error_code=AUTHENTICATION_ERROR_CODES["OIDC_OAUTH_PROVIDER_ERROR"],
                error_message="OIDC_OAUTH_PROVIDER_ERROR",
            )
        # O Plane casa a conta pelo e-mail: so aceita e-mail que o provedor diz ter
        # verificado, para ninguem assumir uma conta afirmando o e-mail de outra pessoa
        # (mesmo cuidado do provedor Gitea, GHSA-7j95-vh8g-f365).
        if user_info_response.get("email_verified") is not True:
            raise AuthenticationException(
                error_code=AUTHENTICATION_ERROR_CODES["OAUTH_PROVIDER_UNVERIFIED_EMAIL"],
                error_message="OAUTH_PROVIDER_UNVERIFIED_EMAIL",
            )

        super().set_user_data(
            {
                "email": email,
                "user": {
                    "provider_id": str(subject),
                    "email": email,
                    "avatar": user_info_response.get("picture") or "",
                    "first_name": user_info_response.get("given_name")
                    or user_info_response.get("name")
                    or user_info_response.get("preferred_username")
                    or "",
                    "last_name": user_info_response.get("family_name") or "",
                    "is_password_autoset": True,
                },
            }
        )
