/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import Link from "next/link";
// ui
import { Button } from "@plane/propel/button";
// layouts
import DefaultLayout from "@/layouts/default-layout";

export function NotAWorkspaceMember() {
  return (
    <DefaultLayout>
      <div className="grid h-full place-items-center p-4">
        <div className="space-y-8 text-center">
          <div className="space-y-2">
            <h3 className="text-16 font-semibold">Sem autorização!</h3>
            <p className="mx-auto w-1/2 text-13 text-secondary">
              Você não é membro deste workspace. Peça um convite ao administrador do workspace ou verifique seus
              convites pendentes.
            </p>
          </div>
          <div className="flex items-center justify-center gap-2">
            <Link href="/invitations">
              <span>
                <Button variant="secondary">Ver convites pendentes</Button>
              </span>
            </Link>
            <Link href="/create-workspace">
              <span>
                <Button variant="primary">Criar novo workspace</Button>
              </span>
            </Link>
          </div>
        </div>
      </div>
    </DefaultLayout>
  );
}
