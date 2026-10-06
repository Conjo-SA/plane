/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { Building2 } from "lucide-react";
import { observer } from "mobx-react";
import { useParams } from "next/navigation";
import useSWR from "swr";
// plane imports
import { useTranslation } from "@plane/i18n";
import { Breadcrumbs, Header } from "@plane/ui";
// components
import { BreadcrumbLink } from "@/components/common/breadcrumb-link";
import { clientKey, conjoBillingService } from "@/components/conjo-clients/helpers";

export const WorkspaceClientsHeader = observer(function WorkspaceClientsHeader() {
  const { workspaceSlug, clientId } = useParams();
  const { t } = useTranslation();
  const slug = workspaceSlug?.toString() ?? "";
  const id = clientId?.toString();
  // same key as the page, so SWR shares the request
  const { data: client } = useSWR(slug && id ? clientKey(slug, id) : null, () =>
    conjoBillingService.getClient(slug, id ?? "")
  );

  return (
    <Header>
      <Header.LeftItem>
        <Breadcrumbs>
          <Breadcrumbs.Item
            component={
              <BreadcrumbLink
                label={t("sidebar.clients")}
                href={`/${slug}/clients`}
                icon={<Building2 className="h-4 w-4 text-tertiary" />}
              />
            }
          />
          {client && (
            <Breadcrumbs.Item
              component={<BreadcrumbLink label={client.name} href={`/${slug}/clients/${client.id}`} />}
            />
          )}
        </Breadcrumbs>
      </Header.LeftItem>
    </Header>
  );
});
