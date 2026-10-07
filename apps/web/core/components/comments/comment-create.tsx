/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
import { useRef, useState } from "react";
import { Controller, useForm } from "react-hook-form";
// plane imports
import { EIssueCommentAccessSpecifier } from "@plane/constants";
import { GlobeIcon, LockIcon } from "@plane/propel/icons";
import type { EditorRefApi } from "@plane/editor";
import type { TCommentsOperations, TIssueComment } from "@plane/types";
import { cn, isCommentEmpty } from "@plane/utils";
// components
import { LiteTextEditor } from "@/components/editor/lite-text";
// hooks
import { useWorkspace } from "@/hooks/store/use-workspace";
// services
import { FileService } from "@/services/file.service";

type TCommentCreate = {
  entityId: string;
  workspaceSlug: string;
  activityOperations: TCommentsOperations;
  showToolbarInitially?: boolean;
  projectId?: string;
  /** Lets the author choose between an internal note and a public reply. */
  showAccessSpecifier?: boolean;
  /**
   * Conjo: who reads public replies (a ticket from the request portal). When set, the choice is shown as a
   * clear switch above the box instead of two small icons in the toolbar; null means a requester we can't name.
   */
  publicAudience?: { name?: string; email?: string } | null;
  onSubmitCallback?: (elementId: string) => void;
};

// services
const fileService = new FileService();

// Same accent as the "waiting for you" color on the request portal.
const PUBLIC_COLOR = "#C2410C";

/** Internal note or reply to the requester, chosen before writing (public replies show on the portal). */
function CommentAudienceSwitch(props: {
  isPublic: boolean;
  audience: { name?: string; email?: string } | null | undefined;
  onChange: (isPublic: boolean) => void;
}) {
  const { isPublic, audience, onChange } = props;
  const who =
    audience?.name && audience?.email ? `${audience.name} (${audience.email})` : audience?.email || audience?.name;
  const options = [
    { key: false, label: "Nota interna", icon: LockIcon },
    { key: true, label: "Resposta ao cliente", icon: GlobeIcon },
  ];
  return (
    <div className="mb-2 flex flex-col gap-1.5">
      <div
        className="flex w-fit rounded-md border border-subtle p-0.5"
        role="radiogroup"
        aria-label="Quem vê este comentário"
      >
        {options.map(({ key, label, icon: Icon }) => {
          const active = isPublic === key;
          return (
            <button
              key={label}
              type="button"
              role="radio"
              aria-checked={active}
              onClick={() => onChange(key)}
              className={cn(
                "flex items-center gap-1.5 rounded-sm px-2.5 py-1 text-caption-md-medium transition-colors",
                active ? "bg-layer-2 text-primary shadow-raised-100" : "text-tertiary hover:text-secondary"
              )}
              style={active && key ? { color: PUBLIC_COLOR } : undefined}
            >
              <Icon className="size-3.5" />
              {label}
            </button>
          );
        })}
      </div>
      <p className="text-caption-sm-regular text-tertiary">
        {isPublic ? (
          <>
            <span style={{ color: PUBLIC_COLOR }}>Visível no portal</span>
            {who ? ` para ${who}` : " para quem abriu o chamado"}, em Meus chamados.
          </>
        ) : (
          'Só a equipe vê. Escolha "Resposta ao cliente" para responder pelo portal.'
        )}
      </p>
    </div>
  );
}

export const CommentCreate = observer(function CommentCreate(props: TCommentCreate) {
  const {
    workspaceSlug,
    entityId,
    activityOperations,
    showToolbarInitially = false,
    projectId,
    showAccessSpecifier = false,
    publicAudience,
    onSubmitCallback,
  } = props;
  const showAudienceSwitch = showAccessSpecifier && publicAudience !== undefined;
  // states
  const [uploadedAssetIds, setUploadedAssetIds] = useState<string[]>([]);
  // refs
  const editorRef = useRef<EditorRefApi>(null);
  // store hooks
  const workspaceStore = useWorkspace();
  // derived values
  const workspaceId = workspaceStore.getWorkspaceBySlug(workspaceSlug)?.id as string;
  // form info
  const {
    handleSubmit,
    control,
    watch,
    formState: { isSubmitting },
    reset,
  } = useForm<Partial<TIssueComment>>({
    defaultValues: {
      comment_html: "<p></p>",
    },
  });

  const onSubmit = async (formData: Partial<TIssueComment>) => {
    try {
      const comment = await activityOperations.createComment(formData);
      if (comment?.id) onSubmitCallback?.(comment.id);
      if (uploadedAssetIds.length > 0) {
        if (projectId) {
          await fileService.updateBulkProjectAssetsUploadStatus(workspaceSlug, projectId.toString(), entityId, {
            asset_ids: uploadedAssetIds,
          });
        } else {
          await fileService.updateBulkWorkspaceAssetsUploadStatus(workspaceSlug, entityId, {
            asset_ids: uploadedAssetIds,
          });
        }
        setUploadedAssetIds([]);
      }
    } catch (error) {
      console.error(error);
    } finally {
      reset({
        comment_html: "<p></p>",
      });
      editorRef.current?.clearEditor();
    }
  };

  const commentHTML = watch("comment_html");
  const isEmpty = isCommentEmpty(commentHTML ?? undefined);

  return (
    <div
      role="group"
      aria-label="Novo comentário"
      className={cn("sticky bottom-0 z-[4] bg-surface-1 sm:static")}
      onKeyDown={(e) => {
        if (
          e.key === "Enter" &&
          !e.shiftKey &&
          !e.ctrlKey &&
          !e.metaKey &&
          !isEmpty &&
          !isSubmitting &&
          editorRef.current?.isEditorReadyToDiscard()
        )
          handleSubmit(onSubmit)(e);
      }}
    >
      <Controller
        name="access"
        control={control}
        render={({ field: { onChange: onAccessChange, value: accessValue } }) => (
          <>
            {showAudienceSwitch && (
              <CommentAudienceSwitch
                isPublic={accessValue === EIssueCommentAccessSpecifier.EXTERNAL}
                audience={publicAudience}
                onChange={(isPublic) =>
                  onAccessChange(
                    isPublic ? EIssueCommentAccessSpecifier.EXTERNAL : EIssueCommentAccessSpecifier.INTERNAL
                  )
                }
              />
            )}
            <div
              className={cn("rounded-md", {
                "ring-1 ring-offset-0": showAudienceSwitch && accessValue === EIssueCommentAccessSpecifier.EXTERNAL,
              })}
              style={
                showAudienceSwitch && accessValue === EIssueCommentAccessSpecifier.EXTERNAL
                  ? ({ "--tw-ring-color": PUBLIC_COLOR } as React.CSSProperties)
                  : undefined
              }
            >
              <Controller
                name="comment_html"
                control={control}
                render={({ field: { value, onChange } }) => (
                  <LiteTextEditor
                    editable
                    workspaceId={workspaceId}
                    id={"add_comment_" + entityId}
                    value={"<p></p>"}
                    workspaceSlug={workspaceSlug}
                    projectId={projectId}
                    onEnterKeyPress={(e) => {
                      if (!isEmpty && !isSubmitting) {
                        handleSubmit(onSubmit)(e);
                      }
                    }}
                    ref={editorRef}
                    initialValue={value ?? "<p></p>"}
                    containerClassName="min-h-min"
                    onChange={(comment_json, comment_html) => onChange(comment_html)}
                    accessSpecifier={accessValue ?? EIssueCommentAccessSpecifier.INTERNAL}
                    handleAccessChange={onAccessChange}
                    showAccessSpecifier={showAccessSpecifier && !showAudienceSwitch}
                    isSubmitting={isSubmitting}
                    uploadFile={async (blockId, file) => {
                      const { asset_id } = await activityOperations.uploadCommentAsset(blockId, file);
                      setUploadedAssetIds((prev) => [...prev, asset_id]);
                      return asset_id;
                    }}
                    duplicateFile={async (assetId: string) => {
                      const { asset_id } = await activityOperations.duplicateCommentAsset(assetId);
                      setUploadedAssetIds((prev) => [...prev, asset_id]);
                      return asset_id;
                    }}
                    showToolbarInitially={showToolbarInitially}
                    parentClassName="p-2"
                    displayConfig={{
                      fontSize: "small-font",
                    }}
                  />
                )}
              />
            </div>
          </>
        )}
      />
    </div>
  );
});
