/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

export const generateFileName = (fileName: string) => {
  const date = new Date();
  const timestamp = date.getTime();

  const _fileName = getFileName(fileName);
  const nameWithoutExtension = _fileName.length > 80 ? _fileName.substring(0, 80) : _fileName;
  const extension = getFileExtension(fileName);

  return `${nameWithoutExtension}-${timestamp}.${extension}`;
};

export const getFileExtension = (filename: string) => filename.slice(((filename.lastIndexOf(".") - 1) >>> 0) + 2);

export const getFileName = (fileName: string) => {
  const dotIndex = fileName.lastIndexOf(".");

  const nameWithoutExtension = fileName.substring(0, dotIndex);

  return nameWithoutExtension;
};

export const convertBytesToSize = (bytes: number) => {
  let size;

  if (bytes < 1024 * 1024) {
    size = Math.round(bytes / 1024) + " KB";
  } else {
    size = Math.round(bytes / (1024 * 1024)) + " MB";
  }

  return size;
};

/** Media an attachment can be previewed as, without downloading it. */
export type TAttachmentPreviewKind = "image" | "video" | "audio" | "pdf";

// SVG is intentionally absent: it can carry scripts, so it is never previewed.
const PREVIEW_MIME_TYPES: Record<string, TAttachmentPreviewKind> = {
  "image/jpeg": "image",
  "image/jpg": "image",
  "image/png": "image",
  "image/gif": "image",
  "image/webp": "image",
  "image/bmp": "image",
  "image/avif": "image",
  "video/mp4": "video",
  "video/webm": "video",
  "video/ogg": "video",
  "video/quicktime": "video",
  "audio/mpeg": "audio",
  "audio/mp3": "audio",
  "audio/wav": "audio",
  "audio/x-wav": "audio",
  "audio/ogg": "audio",
  "audio/webm": "audio",
  "audio/aac": "audio",
  "audio/mp4": "audio",
  "application/pdf": "pdf",
};

const PREVIEW_EXTENSIONS: Record<string, TAttachmentPreviewKind> = {
  jpg: "image",
  jpeg: "image",
  png: "image",
  gif: "image",
  webp: "image",
  bmp: "image",
  avif: "image",
  mp4: "video",
  webm: "video",
  ogv: "video",
  mov: "video",
  mp3: "audio",
  wav: "audio",
  ogg: "audio",
  m4a: "audio",
  aac: "audio",
  pdf: "pdf",
};

/**
 * Resolve how an attachment can be previewed inline.
 * The stored MIME type wins; the extension is only a fallback for older uploads
 * that were saved without one.
 * @returns the preview kind, or undefined when the file has to be downloaded
 */
export const getAttachmentPreviewKind = (
  mimeType?: string | null,
  fileName?: string | null
): TAttachmentPreviewKind | undefined => {
  const normalizedMimeType = (mimeType ?? "").split(";")[0]?.trim().toLowerCase();
  if (normalizedMimeType && PREVIEW_MIME_TYPES[normalizedMimeType]) return PREVIEW_MIME_TYPES[normalizedMimeType];

  const extension = getFileExtension(fileName ?? "").toLowerCase();
  return extension ? PREVIEW_EXTENSIONS[extension] : undefined;
};
