/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

// plane imports
import { API_BASE_URL } from "@plane/constants";
import type {
    TIntakePortal,
    TIntakePortalAssetUpload,
    TIntakePortalMeta,
    TIntakePortalSubmission,
    TIntakePortalSubmissionResponse,
} from "@plane/types";
// api service
import { APIService } from "../api.service";

/**
 * Service class for the public intake portal, the anonymous request form that
 * external requesters use to submit work items into a project's intake.
 * @extends {APIService}
 */
export class IntakePortalService extends APIService {
    constructor(BASE_URL?: string) {
        super(BASE_URL || API_BASE_URL);
    }

    /**
     * Retrieves the public presentation data of a request form.
     * @param {string} anchor - The portal anchor
     * @param {string} [tag] - Optional tag from the URL, applied to submissions
     * @returns {Promise<TIntakePortalMeta>} The portal metadata
     * @throws {Error} If the API request fails
     */
    async retrieveMeta(anchor: string, tag?: string): Promise<TIntakePortalMeta> {
        return this.get(`/api/public/intake-portal/${anchor}/`, { params: tag ? { tag } : {} })
            .then((response) => response?.data)
            .catch((error) => {
                throw error?.response;
            });
    }

    /**
     * Submits a work item through the public request form.
     * @param {string} anchor - The portal anchor
     * @param {TIntakePortalSubmission} data - The submission payload
     * @returns {Promise<TIntakePortalSubmissionResponse>} The created work item reference
     * @throws {Error} If the API request fails
     */
    async createWorkItem(anchor: string, data: TIntakePortalSubmission): Promise<TIntakePortalSubmissionResponse> {
        return this.post(`/api/public/intake-portal/${anchor}/work-items/`, data)
            .then((response) => response?.data)
            .catch((error) => {
                throw error?.response;
            });
    }

    /**
     * Requests a presigned upload for an attachment.
     * @param {string} anchor - The portal anchor
     * @param {File} file - The file to upload
     * @returns {Promise<TIntakePortalAssetUpload>} The presigned upload data
     * @throws {Error} If the API request fails
     */
    async createAssetUpload(anchor: string, file: File): Promise<TIntakePortalAssetUpload> {
        return this.post(`/api/public/intake-portal/${anchor}/assets/`, {
            name: file.name,
            type: file.type,
            size: file.size,
        })
            .then((response) => response?.data)
            .catch((error) => {
                throw error?.response;
            });
    }

    /**
     * Marks an attachment as uploaded once the storage upload succeeds.
     * @param {string} anchor - The portal anchor
     * @param {string} assetId - The asset identifier
     * @throws {Error} If the API request fails
     */
    async completeAssetUpload(anchor: string, assetId: string): Promise<void> {
        return this.patch(`/api/public/intake-portal/${anchor}/assets/${assetId}/`)
            .then((response) => response?.data)
            .catch((error) => {
                throw error?.response;
            });
    }

    /**
     * Uploads an attachment straight to object storage and returns its asset id.
     * The file never passes through the API, only the presigned contract does.
     * @param {string} anchor - The portal anchor
     * @param {File} file - The file to upload
     * @returns {Promise<string>} The uploaded asset identifier
     * @throws {Error} If any step of the upload fails
     */
    async uploadAsset(anchor: string, file: File): Promise<string> {
        const { upload_data, asset_id } = await this.createAssetUpload(anchor, file);

        const formData = new FormData();
        Object.entries(upload_data.fields).forEach(([key, value]) => formData.append(key, value));
        formData.append("file", file);

        const uploadResponse = await fetch(upload_data.url, { method: "POST", body: formData });
        if (!uploadResponse.ok) throw new Error("Upload failed");

        await this.completeAssetUpload(anchor, asset_id);
        return asset_id;
    }

    /**
     * Retrieves the request form configuration of a project.
     * @param {string} workspaceSlug - The workspace slug
     * @param {string} projectId - The project identifier
     * @returns {Promise<TIntakePortal | Record<string, never>>} The portal configuration
     * @throws {Error} If the API request fails
     */
    async retrieveConfig(workspaceSlug: string, projectId: string): Promise<TIntakePortal | Record<string, never>> {
        return this.get(`/api/workspaces/${workspaceSlug}/projects/${projectId}/intake-portal/`)
            .then((response) => response?.data)
            .catch((error) => {
                throw error?.response;
            });
    }

    /**
     * Creates the request form of a project.
     * @param {string} workspaceSlug - The workspace slug
     * @param {string} projectId - The project identifier
     * @param {Partial<TIntakePortal>} data - The portal configuration
     * @returns {Promise<TIntakePortal>} The created portal
     * @throws {Error} If the API request fails
     */
    async createConfig(workspaceSlug: string, projectId: string, data: Partial<TIntakePortal>): Promise<TIntakePortal> {
        return this.post(`/api/workspaces/${workspaceSlug}/projects/${projectId}/intake-portal/`, data)
            .then((response) => response?.data)
            .catch((error) => {
                throw error?.response;
            });
    }

    /**
     * Updates the request form of a project.
     * @param {string} workspaceSlug - The workspace slug
     * @param {string} projectId - The project identifier
     * @param {Partial<TIntakePortal> & { regenerate_anchor?: boolean }} data - The fields to update
     * @returns {Promise<TIntakePortal>} The updated portal
     * @throws {Error} If the API request fails
     */
    async updateConfig(
        workspaceSlug: string,
        projectId: string,
        data: Partial<TIntakePortal> & { regenerate_anchor?: boolean }
    ): Promise<TIntakePortal> {
        return this.patch(`/api/workspaces/${workspaceSlug}/projects/${projectId}/intake-portal/`, data)
            .then((response) => response?.data)
            .catch((error) => {
                throw error?.response;
            });
    }
}
