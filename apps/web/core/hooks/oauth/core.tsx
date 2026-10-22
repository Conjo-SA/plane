/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

// plane imports
import { useSearchParams } from "next/navigation";
import { useTheme } from "next-themes";
import { API_BASE_URL } from "@plane/constants";
import type { TOAuthConfigs, TOAuthOption } from "@plane/types";
// assets
import conjoLogo from "@/app/assets/logos/conjo-logo-black.png?url";
import giteaLogo from "@/app/assets/logos/gitea-logo.svg?url";
import GithubLightLogo from "@/app/assets/logos/github-black.png?url";
import GithubDarkLogo from "@/app/assets/logos/github-dark.svg?url";
import gitlabLogo from "@/app/assets/logos/gitlab-logo.svg?url";
import googleLogo from "@/app/assets/logos/google-logo.svg?url";
// hooks
import { useInstance } from "@/hooks/store/use-instance";

export const useCoreOAuthConfig = (oauthActionText: string): TOAuthConfigs => {
  //router
  const searchParams = useSearchParams();
  // query params
  const next_path = searchParams.get("next_path");
  // theme
  const { resolvedTheme } = useTheme();
  // store hooks
  const { config } = useInstance();
  // derived values
  const isOAuthEnabled =
    (config &&
      (config?.is_google_enabled ||
        config?.is_github_enabled ||
        config?.is_gitlab_enabled ||
        config?.is_gitea_enabled ||
        config?.is_oidc_enabled)) ||
    false;
  const oAuthOptions: TOAuthOption[] = [
    // ConjoSA: login pelo conjo-mail (provedor OIDC), primeiro da lista.
    {
      id: "oidc",
      text: `${oauthActionText} com ${config?.oidc_provider_name || "OIDC"}`,
      icon: <img src={conjoLogo} height={18} width={18} alt="" />,
      onClick: () => {
        window.location.assign(
          `${API_BASE_URL}/auth/oidc/${next_path ? `?next_path=${encodeURIComponent(next_path)}` : ``}`
        );
      },
      enabled: config?.is_oidc_enabled,
    },
    {
      id: "google",
      text: `${oauthActionText} com Google`,
      icon: <img src={googleLogo} height={18} width={18} alt="Logo do Google" />,
      onClick: () => {
        window.location.assign(`${API_BASE_URL}/auth/google/${next_path ? `?next_path=${next_path}` : ``}`);
      },
      enabled: config?.is_google_enabled,
    },
    {
      id: "github",
      text: `${oauthActionText} com GitHub`,
      icon: (
        <img
          src={resolvedTheme === "dark" ? GithubDarkLogo : GithubLightLogo}
          height={18}
          width={18}
          alt="Logo do GitHub"
        />
      ),
      onClick: () => {
        window.location.assign(`${API_BASE_URL}/auth/github/${next_path ? `?next_path=${next_path}` : ``}`);
      },
      enabled: config?.is_github_enabled,
    },
    {
      id: "gitlab",
      text: `${oauthActionText} com GitLab`,
      icon: <img src={gitlabLogo} height={18} width={18} alt="Logo do GitLab" />,
      onClick: () => {
        window.location.assign(`${API_BASE_URL}/auth/gitlab/${next_path ? `?next_path=${next_path}` : ``}`);
      },
      enabled: config?.is_gitlab_enabled,
    },
    {
      id: "gitea",
      text: `${oauthActionText} com Gitea`,
      icon: <img src={giteaLogo} height={18} width={18} alt="Logo do Gitea" />,
      onClick: () => {
        window.location.assign(`${API_BASE_URL}/auth/gitea/${next_path ? `?next_path=${next_path}` : ``}`);
      },
      enabled: config?.is_gitea_enabled,
    },
  ];

  return {
    isOAuthEnabled,
    oAuthOptions,
  };
};
