/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { CloseIcon } from "@plane/propel/icons";
import { AlertCircle } from "lucide-react";
import { observer } from "mobx-react";
import Link from "next/link";
import { useState } from "react";
// ui
import { Tooltip } from "@plane/propel/tooltip";
import {
  convertBytesToSize,
  getAttachmentPreviewKind,
  getFileExtension,
  getFileName,
  getFileURL,
  renderFormattedDate,
  truncateText,
} from "@plane/utils";
// icons
//
import { getFileIcon } from "@/components/icons";
// components
import { IssueAttachmentPreviewModal } from "@/components/issues/attachment/attachment-preview-modal";
import { IssueAttachmentDeleteModal } from "@/components/issues/attachment/delete-attachment-modal";
// helpers
// hooks
import { useIssueDetail } from "@/hooks/store/use-issue-detail";
import { useMember } from "@/hooks/store/use-member";
import { usePlatformOS } from "@/hooks/use-platform-os";
// types
import type { TAttachmentHelpers } from "../issue-detail-widgets/attachments/helper";

type TAttachmentOperationsRemoveModal = Exclude<TAttachmentHelpers, "create">;

type TIssueAttachmentsDetail = {
  attachmentId: string;
  attachmentHelpers: TAttachmentOperationsRemoveModal;
  disabled?: boolean;
};

export const IssueAttachmentsDetail = observer(function IssueAttachmentsDetail(props: TIssueAttachmentsDetail) {
  // props
  const { attachmentId, attachmentHelpers, disabled } = props;
  // store hooks
  const { getUserDetails } = useMember();
  const {
    attachment: { getAttachmentById },
  } = useIssueDetail();
  // state
  const [isDeleteIssueAttachmentModalOpen, setIsDeleteIssueAttachmentModalOpen] = useState(false);
  const [isPreviewModalOpen, setIsPreviewModalOpen] = useState(false);
  // derived values
  const attachment = attachmentId ? getAttachmentById(attachmentId) : undefined;
  const fileName = getFileName(attachment?.attributes.name ?? "");
  const fileExtension = getFileExtension(attachment?.asset_url ?? "");
  const fileIcon = getFileIcon(fileExtension, 28);
  const fileURL = getFileURL(attachment?.asset_url ?? "");
  // Media the browser can render is opened in place, so it never has to be downloaded.
  const previewKind = getAttachmentPreviewKind(attachment?.attributes.type, attachment?.attributes.name);
  const previewURL = fileURL ? `${fileURL}?disposition=inline` : "";
  // hooks
  const { isMobile } = usePlatformOS();

  if (!attachment) return <></>;

  const attachmentSummary = (
    <div className="flex items-center gap-3">
      <div className="h-7 w-7">{fileIcon}</div>
      <div className="flex flex-col gap-1">
        <div className="flex items-center gap-2">
          <Tooltip tooltipContent={fileName} isMobile={isMobile}>
            <span className="text-13">{truncateText(`${fileName}`, 10)}</span>
          </Tooltip>
          <Tooltip
            isMobile={isMobile}
            tooltipContent={`${
              getUserDetails(attachment.updated_by)?.display_name ?? ""
            } uploaded on ${renderFormattedDate(attachment.updated_at)}`}
          >
            <span>
              <AlertCircle className="h-3 w-3" />
            </span>
          </Tooltip>
        </div>

        <div className="flex items-center gap-3 text-11 text-secondary">
          <span>{fileExtension.toUpperCase()}</span>
          <span>{convertBytesToSize(attachment.attributes.size)}</span>
        </div>
      </div>
    </div>
  );

  return (
    <>
      {isDeleteIssueAttachmentModalOpen && (
        <IssueAttachmentDeleteModal
          isOpen={isDeleteIssueAttachmentModalOpen}
          onClose={() => setIsDeleteIssueAttachmentModalOpen(false)}
          attachmentOperations={attachmentHelpers.operations}
          attachmentId={attachmentId}
        />
      )}
      {previewKind && isPreviewModalOpen && (
        <IssueAttachmentPreviewModal
          isOpen={isPreviewModalOpen}
          onClose={() => setIsPreviewModalOpen(false)}
          previewUrl={previewURL}
          downloadUrl={fileURL ?? ""}
          fileName={attachment.attributes.name}
          kind={previewKind}
        />
      )}
      <div className="flex h-[60px] items-center justify-between gap-1 rounded-md border-[2px] border-subtle bg-surface-1 px-4 py-2 text-13">
        {previewKind ? (
          <button type="button" className="min-w-0 text-left" onClick={() => setIsPreviewModalOpen(true)}>
            {attachmentSummary}
          </button>
        ) : (
          // non-previewable files still open inline, letting the browser render them when possible
          <Link href={previewURL} target="_blank" rel="noopener noreferrer">
            {attachmentSummary}
          </Link>
        )}

        {!disabled && (
          <button type="button" onClick={() => setIsDeleteIssueAttachmentModalOpen(true)}>
            <CloseIcon className="h-4 w-4 text-secondary hover:text-primary" />
          </button>
        )}
      </div>
    </>
  );
});
