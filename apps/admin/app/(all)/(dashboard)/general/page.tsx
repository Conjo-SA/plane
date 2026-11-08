/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
import useSWR from "swr";
// components
import { PageWrapper } from "@/components/common/page-wrapper";
// hooks
import { useInstance } from "@/hooks/store";
// local imports
import { GeneralConfigurationForm } from "./form";
import { HourRateForm } from "./hour-rate-form";
// types
import type { Route } from "./+types/page";

function GeneralPage() {
  const { instance, instanceAdmins, formattedConfig, fetchInstanceConfigurations } = useInstance();

  useSWR("INSTANCE_CONFIGURATIONS", () => fetchInstanceConfigurations());

  return (
    <PageWrapper
      header={{
        title: "Configurações gerais",
        description:
          "Altere o nome da sua instância e os e-mails dos administradores. Ative ou desative a telemetria da instância.",
      }}
    >
      <div className="space-y-10">
        {instance && instanceAdmins && <GeneralConfigurationForm instance={instance} instanceAdmins={instanceAdmins} />}
        {formattedConfig && <HourRateForm config={formattedConfig} />}
      </div>
    </PageWrapper>
  );
}

export const meta: Route.MetaFunction = () => [{ title: "Configurações gerais - Administração" }];

export default observer(GeneralPage);
