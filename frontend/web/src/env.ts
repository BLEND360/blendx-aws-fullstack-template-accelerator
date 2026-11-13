/** Boot configuration: only what the bundle needs to start and to sign in.
 * Everything else the deployment decides comes from GET /api/v1/configuration. */

export interface CognitoConfig {
  region: string;
  userPoolId: string;
  appClientId: string;
  domain: string;
}

export interface BootConfig {
  cognito: CognitoConfig;
  /** No identity provider configured: skip sign-in and trust the backend's local bypass. */
  isLocalMode: boolean;
}

type RawEnv = Record<string, string | undefined>;

export function readBootConfig(raw: RawEnv): BootConfig {
  const cognito: CognitoConfig = {
    region: raw.VITE_COGNITO_REGION ?? "",
    userPoolId: raw.VITE_COGNITO_USER_POOL_ID ?? "",
    appClientId: raw.VITE_COGNITO_APP_CLIENT_ID ?? "",
    domain: raw.VITE_COGNITO_DOMAIN ?? "",
  };
  return { cognito, isLocalMode: !(cognito.userPoolId && cognito.appClientId && cognito.domain) };
}

export const { cognito, isLocalMode } = readBootConfig(import.meta.env);
