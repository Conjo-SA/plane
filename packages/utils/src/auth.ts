/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { ReactNode } from "react";
// plane imports
import type { TAuthErrorInfo } from "@plane/constants";
import { E_PASSWORD_STRENGTH, EErrorAlertType, EAuthErrorCodes } from "@plane/constants";

/**
 * @description Password strength levels
 */
export enum PasswordStrength {
  EMPTY = "empty",
  WEAK = "weak",
  FAIR = "fair",
  GOOD = "good",
  STRONG = "strong",
}

/**
 * Calculate password strength based on various criteria
 */
export const getPasswordStrength = (password: string): E_PASSWORD_STRENGTH => {
  if (!password || password === "" || password.length <= 0) {
    return E_PASSWORD_STRENGTH.EMPTY;
  }

  if (password.length < 8) {
    return E_PASSWORD_STRENGTH.LENGTH_NOT_VALID;
  }

  // Check all criteria
  const hasUpperCase = /[A-Z]/.test(password);
  const hasLowerCase = /[a-z]/.test(password);
  const hasDigit = /[0-9]/.test(password);
  const hasSpecialChar = /[!@#$%^&*()\-_+=\[\]{}|;:'",.<>?/]/.test(password);

  if (hasUpperCase && hasLowerCase && hasDigit && hasSpecialChar) {
    return E_PASSWORD_STRENGTH.STRENGTH_VALID;
  }

  return E_PASSWORD_STRENGTH.STRENGTH_NOT_VALID;
};

export type PasswordCriteria = {
  key: string;
  label: string;
  isValid: boolean;
};

/**
 * Get password criteria for validation display
 */
export const getPasswordCriteria = (password: string): PasswordCriteria[] => [
  {
    key: "length",
    label: "Mín. 8 caracteres",
    isValid: password.length >= 8,
  },
  {
    key: "uppercase",
    label: "Mín. 1 letra maiúscula",
    isValid: /[A-Z]/.test(password),
  },
  {
    key: "lowercase",
    label: "Mín. 1 letra minúscula",
    isValid: /[a-z]/.test(password),
  },
  {
    key: "number",
    label: "Mín. 1 número",
    isValid: /[0-9]/.test(password),
  },
  {
    key: "special",
    label: "Mín. 1 caractere especial",
    isValid: /[!@#$%^&*()\-_+=\[\]{}|;:'",.<>?/]/.test(password),
  },
];

// Error code messages
const errorCodeMessages: {
  [key in EAuthErrorCodes]: { title: string; message: (email?: string) => ReactNode };
} = {
  // global
  [EAuthErrorCodes.INSTANCE_NOT_CONFIGURED]: {
    title: `Instância não configurada`,
    message: () => `Instância não configurada. Entre em contato com o administrador.`,
  },
  [EAuthErrorCodes.SIGNUP_DISABLED]: {
    title: `Cadastro desativado`,
    message: () => `Cadastro desativado. Entre em contato com o administrador.`,
  },
  [EAuthErrorCodes.INVALID_PASSWORD]: {
    title: `Senha inválida`,
    message: () => `Senha inválida. Tente novamente.`,
  },
  [EAuthErrorCodes.PASSWORD_TOO_WEAK]: {
    title: `Senha muito fraca`,
    message: () => `Use uma senha mais forte.`,
  },
  [EAuthErrorCodes.SMTP_NOT_CONFIGURED]: {
    title: `SMTP não configurado`,
    message: () => `SMTP não configurado. Entre em contato com o administrador.`,
  },
  // email check in both sign up and sign in
  [EAuthErrorCodes.INVALID_EMAIL]: {
    title: `E-mail inválido`,
    message: () => `E-mail inválido. Tente novamente.`,
  },
  [EAuthErrorCodes.EMAIL_REQUIRED]: {
    title: `E-mail obrigatório`,
    message: () => `E-mail obrigatório. Tente novamente.`,
  },
  // sign up
  [EAuthErrorCodes.USER_ALREADY_EXIST]: {
    title: `Usuário já existe`,
    message: () => `Sua conta já está cadastrada. Entre agora.`,
  },
  [EAuthErrorCodes.REQUIRED_EMAIL_PASSWORD_SIGN_UP]: {
    title: `E-mail e senha obrigatórios`,
    message: () => `E-mail e senha obrigatórios. Tente novamente.`,
  },
  [EAuthErrorCodes.AUTHENTICATION_FAILED_SIGN_UP]: {
    title: `Falha na autenticação`,
    message: () => `Falha na autenticação. Tente novamente.`,
  },
  [EAuthErrorCodes.INVALID_EMAIL_SIGN_UP]: {
    title: `E-mail inválido`,
    message: () => `E-mail inválido. Tente novamente.`,
  },
  [EAuthErrorCodes.MAGIC_SIGN_UP_EMAIL_CODE_REQUIRED]: {
    title: `E-mail e código obrigatórios`,
    message: () => `E-mail e código obrigatórios. Tente novamente.`,
  },
  [EAuthErrorCodes.INVALID_EMAIL_MAGIC_SIGN_UP]: {
    title: `E-mail inválido`,
    message: () => `E-mail inválido. Tente novamente.`,
  },
  // sign in
  [EAuthErrorCodes.BOT_USER_LOGIN_FORBIDDEN]: {
    title: `Acesso não permitido`,
    message: () => `Esta conta não pode ser usada para entrar. Use uma conta pessoal.`,
  },
  [EAuthErrorCodes.USER_ACCOUNT_DEACTIVATED]: {
    title: `Conta de usuário desativada`,
    message: () => `Conta de usuário desativada. Entre em contato com o administrador.`,
  },
  [EAuthErrorCodes.USER_DOES_NOT_EXIST]: {
    title: `Usuário não existe`,
    message: () => `Nenhuma conta encontrada. Crie uma para começar.`,
  },
  [EAuthErrorCodes.REQUIRED_EMAIL_PASSWORD_SIGN_IN]: {
    title: `E-mail e senha obrigatórios`,
    message: () => `E-mail e senha obrigatórios. Tente novamente.`,
  },
  [EAuthErrorCodes.AUTHENTICATION_FAILED_SIGN_IN]: {
    title: `Falha na autenticação`,
    message: () => `Falha na autenticação. Tente novamente.`,
  },
  [EAuthErrorCodes.INVALID_EMAIL_SIGN_IN]: {
    title: `E-mail inválido`,
    message: () => `E-mail inválido. Tente novamente.`,
  },
  [EAuthErrorCodes.MAGIC_SIGN_IN_EMAIL_CODE_REQUIRED]: {
    title: `E-mail e código obrigatórios`,
    message: () => `E-mail e código obrigatórios. Tente novamente.`,
  },
  [EAuthErrorCodes.INVALID_EMAIL_MAGIC_SIGN_IN]: {
    title: `E-mail inválido`,
    message: () => `E-mail inválido. Tente novamente.`,
  },
  // Both Sign in and Sign up
  [EAuthErrorCodes.INVALID_MAGIC_CODE_SIGN_IN]: {
    title: `Falha na autenticação`,
    message: () => `Código de acesso inválido. Tente novamente.`,
  },
  [EAuthErrorCodes.INVALID_MAGIC_CODE_SIGN_UP]: {
    title: `Falha na autenticação`,
    message: () => `Código de acesso inválido. Tente novamente.`,
  },
  [EAuthErrorCodes.EXPIRED_MAGIC_CODE_SIGN_IN]: {
    title: `Código de acesso expirado`,
    message: () => `Código de acesso expirado. Tente novamente.`,
  },
  [EAuthErrorCodes.EXPIRED_MAGIC_CODE_SIGN_UP]: {
    title: `Código de acesso expirado`,
    message: () => `Código de acesso expirado. Tente novamente.`,
  },
  [EAuthErrorCodes.EMAIL_CODE_ATTEMPT_EXHAUSTED_SIGN_IN]: {
    title: `Código de acesso expirado`,
    message: () => `Código de acesso expirado. Tente novamente.`,
  },
  [EAuthErrorCodes.EMAIL_CODE_ATTEMPT_EXHAUSTED_SIGN_UP]: {
    title: `Código de acesso expirado`,
    message: () => `Código de acesso expirado. Tente novamente.`,
  },
  // Oauth
  [EAuthErrorCodes.OAUTH_NOT_CONFIGURED]: {
    title: `OAuth não configurado`,
    message: () => `OAuth não configurado. Entre em contato com o administrador.`,
  },
  [EAuthErrorCodes.GOOGLE_NOT_CONFIGURED]: {
    title: `Google não configurado`,
    message: () => `Google não configurado. Entre em contato com o administrador.`,
  },
  [EAuthErrorCodes.GITHUB_NOT_CONFIGURED]: {
    title: `GitHub não configurado`,
    message: () => `GitHub não configurado. Entre em contato com o administrador.`,
  },
  [EAuthErrorCodes.GITLAB_NOT_CONFIGURED]: {
    title: `GitLab não configurado`,
    message: () => `GitLab não configurado. Entre em contato com o administrador.`,
  },
  [EAuthErrorCodes.GOOGLE_OAUTH_PROVIDER_ERROR]: {
    title: `Erro no provedor OAuth do Google`,
    message: () => `Erro no provedor OAuth do Google. Tente novamente.`,
  },
  [EAuthErrorCodes.GITHUB_OAUTH_PROVIDER_ERROR]: {
    title: `Erro no provedor OAuth do GitHub`,
    message: () => `Erro no provedor OAuth do GitHub. Tente novamente.`,
  },
  [EAuthErrorCodes.GITLAB_OAUTH_PROVIDER_ERROR]: {
    title: `Erro no provedor OAuth do GitLab`,
    message: () => `Erro no provedor OAuth do GitLab. Tente novamente.`,
  },
  // Reset Password
  [EAuthErrorCodes.INVALID_PASSWORD_TOKEN]: {
    title: `Token de senha inválido`,
    message: () => `Token de senha inválido. Tente novamente.`,
  },
  [EAuthErrorCodes.EXPIRED_PASSWORD_TOKEN]: {
    title: `Token de senha expirado`,
    message: () => `Token de senha expirado. Tente novamente.`,
  },
  // Change password
  [EAuthErrorCodes.MISSING_PASSWORD]: {
    title: `Senha obrigatória`,
    message: () => `Senha obrigatória. Tente novamente.`,
  },
  [EAuthErrorCodes.INCORRECT_OLD_PASSWORD]: {
    title: `Senha atual incorreta`,
    message: () => `Senha atual incorreta. Tente novamente.`,
  },
  [EAuthErrorCodes.INVALID_NEW_PASSWORD]: {
    title: `Nova senha inválida`,
    message: () => `Nova senha inválida. Tente novamente.`,
  },
  // set password
  [EAuthErrorCodes.PASSWORD_ALREADY_SET]: {
    title: `Senha já definida`,
    message: () => `Senha já definida. Tente novamente.`,
  },
  // admin
  [EAuthErrorCodes.ADMIN_ALREADY_EXIST]: {
    title: `Administrador já existe`,
    message: () => `Administrador já existe. Tente novamente.`,
  },
  [EAuthErrorCodes.REQUIRED_ADMIN_EMAIL_PASSWORD_FIRST_NAME]: {
    title: `E-mail, senha e nome obrigatórios`,
    message: () => `E-mail, senha e nome obrigatórios. Tente novamente.`,
  },
  [EAuthErrorCodes.INVALID_ADMIN_EMAIL]: {
    title: `E-mail de administrador inválido`,
    message: () => `E-mail de administrador inválido. Tente novamente.`,
  },
  [EAuthErrorCodes.INVALID_ADMIN_PASSWORD]: {
    title: `Senha de administrador inválida`,
    message: () => `Senha de administrador inválida. Tente novamente.`,
  },
  [EAuthErrorCodes.REQUIRED_ADMIN_EMAIL_PASSWORD]: {
    title: `E-mail e senha obrigatórios`,
    message: () => `E-mail e senha obrigatórios. Tente novamente.`,
  },
  [EAuthErrorCodes.ADMIN_AUTHENTICATION_FAILED]: {
    title: `Falha na autenticação`,
    message: () => `Falha na autenticação. Tente novamente.`,
  },
  [EAuthErrorCodes.ADMIN_USER_ALREADY_EXIST]: {
    title: `Usuário administrador já existe`,
    message: () => `Usuário administrador já existe. Entre agora.`,
  },
  [EAuthErrorCodes.ADMIN_USER_DOES_NOT_EXIST]: {
    title: `Usuário administrador não existe`,
    message: () => `Usuário administrador não existe. Entre agora.`,
  },
  [EAuthErrorCodes.MAGIC_LINK_LOGIN_DISABLED]: {
    title: `Acesso por link mágico desativado`,
    message: () => `O acesso por link mágico está desativado. Use sua senha para entrar.`,
  },
  [EAuthErrorCodes.PASSWORD_LOGIN_DISABLED]: {
    title: `Acesso por senha desativado`,
    message: () => `O acesso por senha está desativado. Use o link mágico para entrar.`,
  },
  [EAuthErrorCodes.ADMIN_USER_DEACTIVATED]: {
    title: `Usuário administrador desativado`,
    message: () => `A conta do usuário administrador foi desativada. Entre em contato com o administrador.`,
  },
  [EAuthErrorCodes.RATE_LIMIT_EXCEEDED]: {
    title: `Limite de requisições excedido`,
    message: () => `Muitas requisições. Tente novamente mais tarde.`,
  },
};

// Error handler
export const authErrorHandler = (errorCode: EAuthErrorCodes, email?: string): TAuthErrorInfo | undefined => {
  const bannerAlertErrorCodes = [
    EAuthErrorCodes.INSTANCE_NOT_CONFIGURED,
    EAuthErrorCodes.INVALID_EMAIL,
    EAuthErrorCodes.EMAIL_REQUIRED,
    EAuthErrorCodes.SIGNUP_DISABLED,
    EAuthErrorCodes.INVALID_PASSWORD,
    EAuthErrorCodes.SMTP_NOT_CONFIGURED,
    EAuthErrorCodes.USER_ALREADY_EXIST,
    EAuthErrorCodes.AUTHENTICATION_FAILED_SIGN_UP,
    EAuthErrorCodes.REQUIRED_EMAIL_PASSWORD_SIGN_UP,
    EAuthErrorCodes.INVALID_EMAIL_SIGN_UP,
    EAuthErrorCodes.INVALID_EMAIL_MAGIC_SIGN_UP,
    EAuthErrorCodes.MAGIC_SIGN_UP_EMAIL_CODE_REQUIRED,
    EAuthErrorCodes.USER_DOES_NOT_EXIST,
    EAuthErrorCodes.AUTHENTICATION_FAILED_SIGN_IN,
    EAuthErrorCodes.REQUIRED_EMAIL_PASSWORD_SIGN_IN,
    EAuthErrorCodes.INVALID_EMAIL_SIGN_IN,
    EAuthErrorCodes.INVALID_EMAIL_MAGIC_SIGN_IN,
    EAuthErrorCodes.MAGIC_SIGN_IN_EMAIL_CODE_REQUIRED,
    EAuthErrorCodes.INVALID_MAGIC_CODE_SIGN_IN,
    EAuthErrorCodes.INVALID_MAGIC_CODE_SIGN_UP,
    EAuthErrorCodes.EXPIRED_MAGIC_CODE_SIGN_IN,
    EAuthErrorCodes.EXPIRED_MAGIC_CODE_SIGN_UP,
    EAuthErrorCodes.EMAIL_CODE_ATTEMPT_EXHAUSTED_SIGN_IN,
    EAuthErrorCodes.EMAIL_CODE_ATTEMPT_EXHAUSTED_SIGN_UP,
    EAuthErrorCodes.OAUTH_NOT_CONFIGURED,
    EAuthErrorCodes.GOOGLE_NOT_CONFIGURED,
    EAuthErrorCodes.GITHUB_NOT_CONFIGURED,
    EAuthErrorCodes.GITLAB_NOT_CONFIGURED,
    EAuthErrorCodes.GOOGLE_OAUTH_PROVIDER_ERROR,
    EAuthErrorCodes.GITHUB_OAUTH_PROVIDER_ERROR,
    EAuthErrorCodes.GITLAB_OAUTH_PROVIDER_ERROR,
    EAuthErrorCodes.INVALID_PASSWORD_TOKEN,
    EAuthErrorCodes.EXPIRED_PASSWORD_TOKEN,
    EAuthErrorCodes.INCORRECT_OLD_PASSWORD,
    EAuthErrorCodes.INVALID_NEW_PASSWORD,
    EAuthErrorCodes.PASSWORD_ALREADY_SET,
    EAuthErrorCodes.ADMIN_ALREADY_EXIST,
    EAuthErrorCodes.REQUIRED_ADMIN_EMAIL_PASSWORD_FIRST_NAME,
    EAuthErrorCodes.INVALID_ADMIN_EMAIL,
    EAuthErrorCodes.INVALID_ADMIN_PASSWORD,
    EAuthErrorCodes.REQUIRED_ADMIN_EMAIL_PASSWORD,
    EAuthErrorCodes.ADMIN_AUTHENTICATION_FAILED,
    EAuthErrorCodes.ADMIN_USER_ALREADY_EXIST,
    EAuthErrorCodes.ADMIN_USER_DOES_NOT_EXIST,
    EAuthErrorCodes.BOT_USER_LOGIN_FORBIDDEN,
    EAuthErrorCodes.USER_ACCOUNT_DEACTIVATED,
  ];

  if (bannerAlertErrorCodes.includes(errorCode))
    return {
      type: EErrorAlertType.BANNER_ALERT,
      code: errorCode,
      title: errorCodeMessages[errorCode]?.title || "Erro",
      message: errorCodeMessages[errorCode]?.message(email) || "Algo deu errado. Tente novamente.",
    };

  return undefined;
};
