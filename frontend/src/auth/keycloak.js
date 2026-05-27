import { UserManager } from "oidc-client-ts";

const KEYCLOAK_URL = import.meta.env.VITE_KEYCLOAK_URL;
const REALM = import.meta.env.VITE_KEYCLOAK_REALM;
const CLIENT_ID = import.meta.env.VITE_KEYCLOAK_CLIENT_ID;
const FRONTEND_URL = import.meta.env.VITE_FRONTEND_URL;

export const userManager = new UserManager({
  authority:                 `${KEYCLOAK_URL}/realms/${REALM}`,
  client_id:                 CLIENT_ID,
  redirect_uri:              `${FRONTEND_URL}/callback`,
  post_logout_redirect_uri:  FRONTEND_URL,
  response_type:             "code",
  scope:                     "openid profile email",
  // tự động load user từ storage khi khởi động
  automaticSilentRenew:      true,
  silent_redirect_uri:       `${FRONTEND_URL}/silent-renew`,
});
