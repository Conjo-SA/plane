/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { Download, ExternalLink } from "lucide-react";
// plane imports
import { useTranslation } from "@plane/i18n";
import { CloseIcon } from "@plane/propel/icons";
import { EModalPosition, EModalWidth, ModalCore } from "@plane/ui";
import type { TAttachmentPreviewKind } from "@plane/utils";

type Props = {
    isOpen: boolean;
    onClose: () => void;
    /** URL served with an inline disposition, so the browser renders it in place. */
    previewUrl: string;
    /** URL served with an attachment disposition, for the download action. */
    downloadUrl: string;
    fileName: string;
    kind: TAttachmentPreviewKind;
};

export function IssueAttachmentPreviewModal(props: Props) {
    const { isOpen, onClose, previewUrl, downloadUrl, fileName, kind } = props;
    const { t } = useTranslation();

    return (
        <ModalCore isOpen={isOpen} handleClose={onClose} position={EModalPosition.CENTER} width={EModalWidth.VIXL}>
            <div className="flex max-h-[85vh] flex-col">
                <div className="flex items-center justify-between gap-3 border-b border-subtle px-4 py-3">
                    <p className="truncate text-body-sm-medium text-primary">{fileName}</p>
                    <div className="flex flex-shrink-0 items-center gap-1">
                        <a
                            href={previewUrl}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="rounded-sm p-1.5 text-tertiary transition-colors hover:bg-layer-1 hover:text-primary"
                            aria-label={t("common.actions.open_in_new_tab")}
                        >
                            <ExternalLink className="size-4" />
                        </a>
                        <a
                            href={downloadUrl}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="rounded-sm p-1.5 text-tertiary transition-colors hover:bg-layer-1 hover:text-primary"
                            aria-label={t("common.actions.download")}
                        >
                            <Download className="size-4" />
                        </a>
                        <button
                            type="button"
                            onClick={onClose}
                            className="rounded-sm p-1.5 text-tertiary transition-colors hover:bg-layer-1 hover:text-primary"
                            aria-label={t("close")}
                        >
                            <CloseIcon className="size-4" />
                        </button>
                    </div>
                </div>

                <div className="flex min-h-0 flex-1 items-center justify-center overflow-auto bg-layer-1 p-4">
                    {kind === "image" && (
                        <img src={previewUrl} alt={fileName} className="max-h-[70vh] max-w-full object-contain" />
                    )}
                    {kind === "video" && (
                        // eslint-disable-next-line jsx-a11y/media-has-caption
                        <video src={previewUrl} controls className="max-h-[70vh] max-w-full" />
                    )}
                    {kind === "audio" && (
                        // eslint-disable-next-line jsx-a11y/media-has-caption
                        <audio src={previewUrl} controls className="w-full" />
                    )}
                    {kind === "pdf" && <iframe src={previewUrl} title={fileName} className="h-[70vh] w-full border-0" />}
                </div>
            </div>
        </ModalCore>
    );
}
