# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from plane.authentication.adapter.base import Adapter
from plane.authentication.utils.sso import sso_password_exception, uses_sso
from plane.db.models import User


class CredentialAdapter(Adapter):
    """Common interface for all credential providers"""

    def __init__(self, request, provider, callback=None):
        super().__init__(request=request, provider=provider, callback=callback)
        self.request = request
        self.provider = provider

    def authenticate(self):
        # ConjoSA: conta do SSO so entra pelo SSO (nem senha, nem codigo por e-mail).
        email = str(getattr(self, "key", "") or "").lower().strip()
        if email and uses_sso(User.objects.filter(email=email).first()):
            self.logger.warning("Credential login refused for an SSO account")
            raise sso_password_exception(email=email)
        self.set_user_data()
        return self.complete_login_or_signup()
