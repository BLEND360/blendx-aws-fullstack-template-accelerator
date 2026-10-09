import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// The local API. Production reaches the same paths through CloudFront, so the
// SPA only ever uses origin-relative /api and /auth; this is the one place a
// destination is named, and it is a dev-server constant, not configuration.
const LOCAL_API = "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "^/(api|auth)(/|$)": {
        target: LOCAL_API,
        changeOrigin: false,
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
  },
});
