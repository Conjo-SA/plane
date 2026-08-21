/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { MouseEvent } from "react";
import { useState } from "react";
import { observer } from "mobx-react";
// plane imports
import type { TIssue, TIssueAttachment } from "@plane/types";
import type { TAttachmentPreviewKind } from "@plane/utils";
import { cn, getAttachmentPreviewKind, getFileURL } from "@plane/utils";
// components
import { IssueAttachmentPreviewModal } from "@/components/issues/attachment/attachment-preview-modal";

type TPreviewTarget = {
  previewUrl: string;
  downloadUrl: string;
  fileName: string;
  kind: TAttachmentPreviewKind;
};

type Props = {
  issue: TIssue;
  variant?: "list" | "kanban";
};

const MAX_VISIBLE_THUMBNAILS = 3;

const getAttachmentUrls = (attachment: TIssueAttachment) => {
  const fileURL = getFileURL(attachment?.asset_url ?? "") ?? "";
  return {
    downloadUrl: fileURL,
    // inline disposition lets the browser render the media in place instead of downloading it
    previewUrl: fileURL ? `${fileURL}?disposition=inline` : "",
  };
};

/**
 * Renders image attachments of a work item as inline thumbnails (no download required),
 * opening the shared preview modal on click. Used on list rows and kanban cards.
 */
export const IssueCardAttachmentPreviews = observer(function IssueCardAttachmentPreviews(props: Props) {
  const { issue, variant = "kanban" } = props;
  // state
  const [previewTarget, setPreviewTarget] = useState<TPreviewTarget | null>(null);

  const imageAttachments = (issue?.issue_attachments ?? []).filter(
    (attachment) => getAttachmentPreviewKind(attachment?.attributes?.type, attachment?.attributes?.name) === "image"
  );

  if (imageAttachments.length === 0) return null;

  const visibleAttachments = imageAttachments.slice(0, MAX_VISIBLE_THUMBNAILS);
  const hiddenCount = imageAttachments.length - visibleAttachments.length;

  const handlePreviewClick = (e: MouseEvent, attachment: TIssueAttachment) => {
    // keep the card/row link from navigating when a thumbnail is clicked
    e.preventDefault();
    e.stopPropagation();
    const { previewUrl, downloadUrl } = getAttachmentUrls(attachment);
    if (!previewUrl) return;
    setPreviewTarget({
      previewUrl,
      downloadUrl,
      fileName: attachment.attributes.name,
      kind: "image",
    });
  };

  return (
    <>
      {previewTarget && (
        <IssueAttachmentPreviewModal
          isOpen
          onClose={() => setPreviewTarget(null)}
          previewUrl={previewTarget.previewUrl}
          downloadUrl={previewTarget.downloadUrl}
          fileName={previewTarget.fileName}
          kind={previewTarget.kind}
        />
      )}
      <div className={cn("flex items-center gap-1.5", { "flex-wrap": variant === "kanban" })}>
        {visibleAttachments.map((attachment) => {
          const { previewUrl } = getAttachmentUrls(attachment);
          if (!previewUrl) return null;
          return (
            <button
              key={attachment.id}
              type="button"
              onClick={(e) => handlePreviewClick(e, attachment)}
              className={cn(
                "flex-shrink-0 overflow-hidden rounded-sm border border-subtle bg-layer-1 transition-colors hover:border-strong",
                variant === "kanban" ? "size-14" : "size-5"
              )}
              aria-label={attachment.attributes.name}
            >
              <img
                src={previewUrl}
                alt={attachment.attributes.name}
                className="h-full w-full object-cover"
                loading="lazy"
              />
            </button>
          );
        })}
        {hiddenCount > 0 && <span className="flex-shrink-0 text-11 text-tertiary">+{hiddenCount}</span>}
      </div>
    </>
  );
});
