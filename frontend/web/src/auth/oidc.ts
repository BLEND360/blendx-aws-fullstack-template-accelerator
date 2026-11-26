import { UserManager } from "oidc-client-ts";
import { cognito } from "../env";

let manager: UserManager | null = null;

/** The only place oidc-client-ts is used. Lazy: in local mode there is no
 * identity provider, and constructing a manager without one throws. */
export function getUserManager(): UserManager {
  manager ??= new UserManager({
    authority: `https://cognito-idp.${cognito.region}.amazonaws.com/${cognito.userPoolId}`,
    client_id: cognito.appClientId,
    redirect_uri: `${window.location.origin}/`,
    post_logout_redirect_uri: `${window.location.origin}/`,
    response_type: "code",
    scope: "openid email profile",
    // Cognito's discovery document has no standard end_session_endpoint, and its
    // /logout expects client_id + logout_uri. Seed the real Hosted UI URL so
    // signoutRedirect() reaches it.
    metadataSeed: {
      end_session_endpoint:
        `https://${cognito.domain}/logout?client_id=${cognito.appClientId}` +
        `&logout_uri=${encodeURIComponent(`${window.location.origin}/`)}`,
    },
  });
  return manager;
}
