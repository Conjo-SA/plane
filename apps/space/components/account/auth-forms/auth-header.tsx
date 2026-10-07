/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

// helpers
import { EAuthModes } from "@/types/auth";

type TAuthHeader = {
  authMode: EAuthModes;
};

type TAuthHeaderContent = {
  header: string;
  subHeader: string;
};

type TAuthHeaderDetails = {
  [mode in EAuthModes]: TAuthHeaderContent;
};

const Titles: TAuthHeaderDetails = {
  [EAuthModes.SIGN_IN]: {
    header: "Entre para votar ou comentar",
    subHeader: "Ajude a priorizar as funcionalidades que você quer ver.",
  },
  [EAuthModes.SIGN_UP]: {
    header: "Visualize, comente e muito mais",
    subHeader: "Cadastre-se ou entre para trabalhar com tarefas e páginas do Tasks.",
  },
};

export function AuthHeader(props: TAuthHeader) {
  const { authMode } = props;

  const getHeaderSubHeader = (mode: EAuthModes | null): TAuthHeaderContent => {
    if (mode) {
      return Titles[mode];
    }

    return {
      header: "Comente ou reaja às tarefas",
      subHeader: "Use o Tasks para contribuir com suas sugestões.",
    };
  };

  const { header, subHeader } = getHeaderSubHeader(authMode);

  return (
    <>
      <div className="flex flex-col gap-1">
        <span className="text-20 leading-7 font-semibold text-primary">{header}</span>
        <span className="text-20 leading-7 font-semibold text-placeholder">{subHeader}</span>
      </div>
    </>
  );
}
