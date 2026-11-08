/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useForm } from "react-hook-form";
import { Button } from "@plane/propel/button";
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import type { IFormattedInstanceConfiguration } from "@plane/types";
// components
import { ControllerInput } from "@/components/common/controller-input";
// hooks
import { useInstance } from "@/hooks/store";

type HourRateFormValues = { CONJO_HOUR_RATE: string };

/** "1.500,50" or "1500.5" → "1500.50"; "" stays empty (no value in the report); null when invalid. */
const normalizeRate = (raw: string): string | null => {
  const text = raw.trim();
  if (!text) return "";
  const plain = text.includes(",") ? text.replace(/\./g, "").replace(",", ".") : text;
  if (!/^\d+(\.\d{1,2})?$/.test(plain) || Number(plain) <= 0) return null;
  return Number(plain).toFixed(2);
};

/** Conjo: value of one hour, used in the client activity report e-mail (CONJO-52). */
export function HourRateForm({ config }: { config: IFormattedInstanceConfiguration }) {
  const { updateInstanceConfigurations } = useInstance();
  const {
    handleSubmit,
    control,
    formState: { errors, isSubmitting },
  } = useForm<HourRateFormValues>({
    defaultValues: { CONJO_HOUR_RATE: config["CONJO_HOUR_RATE"] ?? "" },
  });

  const onSubmit = async (formData: HourRateFormValues) => {
    const rate = normalizeRate(formData.CONJO_HOUR_RATE);
    if (rate === null) {
      setToast({ type: TOAST_TYPE.ERROR, title: "Erro!", message: "Informe um valor válido, como 150,00." });
      return;
    }
    await updateInstanceConfigurations({ CONJO_HOUR_RATE: rate })
      .then(() =>
        setToast({ type: TOAST_TYPE.SUCCESS, title: "Sucesso!", message: "Valor da hora atualizado com sucesso" })
      )
      .catch((err) => console.error(err));
  };

  return (
    <div className="space-y-6">
      <div className="border-b border-subtle pb-1.5 text-16 font-medium text-primary">Relatório de clientes</div>
      <div className="grid w-full grid-cols-1 gap-8 lg:grid-cols-2">
        <ControllerInput
          control={control}
          type="text"
          name="CONJO_HOUR_RATE"
          label="Valor da hora (R$)"
          description="Usado para mostrar o valor das horas de evolução no e-mail e no PDF do relatório. Vazio, nenhum valor é mostrado."
          placeholder="150,00"
          error={Boolean(errors.CONJO_HOUR_RATE)}
          required={false}
        />
      </div>
      <Button
        variant="primary"
        size="lg"
        onClick={() => {
          void handleSubmit(onSubmit)();
        }}
        loading={isSubmitting}
      >
        {isSubmitting ? "Salvando" : "Salvar valor da hora"}
      </Button>
    </div>
  );
}
