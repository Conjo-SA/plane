/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

export enum EFileError {
  INVALID_FILE_TYPE = "INVALID_FILE_TYPE",
  FILE_SIZE_TOO_LARGE = "FILE_SIZE_TOO_LARGE",
  NO_FILE_SELECTED = "NO_FILE_SELECTED",
}

type TArgs = {
  acceptedMimeTypes: string[];
  file: File;
  maxFileSize: number;
  onError: (error: EFileError, message: string) => void;
};

export const isFileValid = (args: TArgs): boolean => {
  const { acceptedMimeTypes, file, maxFileSize, onError } = args;

  if (!file) {
    onError(EFileError.NO_FILE_SELECTED, "Nenhum arquivo selecionado. Selecione um arquivo para enviar.");
    return false;
  }

  if (!acceptedMimeTypes.includes(file.type)) {
    onError(EFileError.INVALID_FILE_TYPE, "Tipo de arquivo inválido.");
    return false;
  }

  if (file.size > maxFileSize) {
    onError(
      EFileError.FILE_SIZE_TOO_LARGE,
      `Arquivo muito grande. Selecione um arquivo menor que ${maxFileSize / 1024 / 1024} MB.`
    );
    return false;
  }

  return true;
};
