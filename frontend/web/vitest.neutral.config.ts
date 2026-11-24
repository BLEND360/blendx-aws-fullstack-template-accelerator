import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig, mergeConfig } from "vitest/config";
import base from "./vite.config";

const here = path.dirname(fileURLToPath(import.meta.url));
const realTokens = path.resolve(here, "src/tokens/index.ts");
const neutralTokens = path.resolve(here, "tests/neutral-tokens/index.ts");

// The same suite, with the brand entry point replaced by tests/neutral-tokens.
export default mergeConfig(
  base,
  defineConfig({
    plugins: [
      {
        name: "neutral-tokens",
        enforce: "pre",
        async resolveId(source, importer, options) {
          const resolved = await this.resolve(source, importer, { ...options, skipSelf: true });
          return resolved && path.normalize(resolved.id) === realTokens ? neutralTokens : null;
        },
      },
    ],
    test: {
      // These assert Blend's own tokens (contrast of its palette, its logo variants).
      exclude: ["**/node_modules/**", "src/theme/tokens.test.tsx"],
    },
  }),
);
