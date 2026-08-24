# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from .config import urlpatterns as config_urls
from .server import urlpatterns as server_urls

urlpatterns = [
    *config_urls,
    *server_urls,
]
