import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// The local API. Production reaches the same paths through CloudFront, so the
// SPA only ever uses origin-relative /api and /auth; this is the one place a
// destination is named, and it is a dev-server constant, not configuration.
const LOCAL_API = "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    // Cognito only returns to http://localhost:5173/; a silent hop to another port breaks sign-in.
    strictPort: true,
    proxy: {
      "^/(api|auth)(/|$)": {
        target: LOCAL_API,
        // With the API down the proxy answers 500, which reads as a bug in the
        // app; 503 makes the SPA say the service is unavailable.
        configure: (proxy) => {
          proxy.on("error", (_error, _request, response) => {
            if ("writeHead" in response && !response.headersSent) response.writeHead(503).end();
          });
        },
      },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    // antd renders are slow on shared CI runners; the 5 s default makes the page tests flaky.
    testTimeout: 15_000,
    // A developer's .env (written by deploy_auth.py) must not turn sign-in on under test.
    env: {
      VITE_COGNITO_REGION: "",
      VITE_COGNITO_USER_POOL_ID: "",
      VITE_COGNITO_APP_CLIENT_ID: "",
      VITE_COGNITO_DOMAIN: "",
    },
  },
});
