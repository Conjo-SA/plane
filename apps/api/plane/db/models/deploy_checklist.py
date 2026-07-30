# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Constants for the deploy checklist gate.

The per-project on/off switch is the ``Project.deploy_checklist_enabled`` boolean,
toggled in the UI under Project Settings > Automations. The gate logic lives in
``plane.db.deploy_checklist_gate``.
"""

# Marker stored on the checklist sub-issues so the gate can tell which children it
# owns (and ignore unrelated sub-issues the team may have added by hand).
DEPLOY_CHECKLIST_SOURCE = "deploy-checklist"

# Company-wide deploy checklist. Created as sub-issues when a completion is blocked.
DEFAULT_DEPLOY_CHECKLIST_ITEMS = [
    "Teste em homologação com prova (comentário no ticket)",
    "Conferência das ENVs, se houver",
    "Build concluído com prova",
    "Indicação de que a alteração subiu em PROD com prova",
]
