/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

// ui
import { Button } from "@plane/propel/button";

function ErrorPage() {
  const handleRetry = () => {
    window.location.reload();
  };

  return (
    <div className="grid h-screen place-items-center bg-surface-1 p-4">
      <div className="space-y-8 text-center">
        <div className="space-y-2">
          <h3 className="text-16 font-semibold">Ops! Algo não saiu como esperado.</h3>
          <p className="mx-auto text-13 text-secondary md:w-1/2">
            Algo deu errado do nosso lado. Não se preocupe: nossa equipe já foi notificada. Se tiver mais detalhes,{" "}
            <a href="https://conjosa.com.br" target="_blank" className="text-accent-primary" rel="noopener noreferrer">
              entre em contato com a Conjo SA
            </a>
            .
          </p>
        </div>
        <div className="flex items-center justify-center gap-2">
          <Button variant="primary" size="lg" onClick={handleRetry}>
            Atualizar
          </Button>
          {/* <Button variant="secondary" size="lg" onClick={() => {}}>
            Sair
          </Button> */}
        </div>
      </div>
    </div>
  );
}

export default ErrorPage;
