# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Importing a signals module here registers its receivers. This package is
# imported from plane.db.apps.DbConfig.ready().
from . import deploy_checklist  # noqa: F401
