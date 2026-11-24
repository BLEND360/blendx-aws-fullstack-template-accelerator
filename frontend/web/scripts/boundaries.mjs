// The two rules CI enforces on the web app (the web counterpart of
// infra/tests/test_no_hardcoded_names.py):
//   brand-literal / tokens-internal  Brand lives only behind src/tokens/index.ts.
//   api-base-url                     No file defines or reads an API base URL.
// Textual on purpose: no parser, no dependencies. It does not see named colors
// ("red") or values built at runtime; widen it if one ever leaks.
import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";

const SKIP_DIRS = new Set([
  "node_modules", "dist", ".git", ".kiro", ".claude", ".venv", "cdk.out",
  "__pycache__", ".pytest_cache", ".agents",
]);
const SKIP_FILES = new Set(["uv.lock", "package-lock.json"]);
const TEXT_EXT = new Set([
  ".ts", ".tsx", ".js", ".mjs", ".css", ".html", ".json", ".toml", ".py", ".md", ".yml", ".yaml", ".env", "",
]);
const BRAND_EXT = new Set([".ts", ".tsx", ".css", ".html"]);

const WEB = "frontend/web/";
const TOKENS = `${WEB}src/tokens/`;
const NEUTRAL_TOKENS = `${WEB}tests/neutral-tokens/`;
// The checker and its own test necessarily spell out what they look for.
const SELF = [`${WEB}scripts/`, `${WEB}tests/boundaries.test.ts`];

const HEX = /#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})\b/;
const COLOR_FN = /\b(?:rgba?|hsla?|oklch|oklab)\(/;
// A family literal declared here; `fontFamily: token.fontFamily` is reading the theme, which is fine.
const FONT_FAMILY = /font-family\s*:\s*(?!var\(|inherit)|fontFamily\s*:\s*['"`]/;
const API_BASE_URL = /\bVITE_API\w*|\b\w*API_BASE_URL\b|\bapiBaseUrl\b|\bAPI_URL\b/;
const IMPORT_SPECIFIER = /(?:from\s*|import\s*\(?\s*|@import\s+(?:url\()?\s*|url\(\s*)['"]([^'"]+)['"]/g;
// tokens/<anything>: the directory itself ("../tokens") is the one allowed import.
const TOKENS_INTERNAL = /(?:^|\/)tokens\/[^/]+/;

function* walk(dir) {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    if (entry.isDirectory()) {
      if (!SKIP_DIRS.has(entry.name)) yield* walk(path.join(dir, entry.name));
    } else if (!SKIP_FILES.has(entry.name)) {
      yield path.join(dir, entry.name);
    }
  }
}

/**
 * @param {string} root repository root
 * @returns {{file: string, line: number, rule: string}[]}
 */
export function scan(root) {
  const violations = [];
  for (const abs of walk(root)) {
    const file = path.relative(root, abs).split(path.sep).join("/");
    const ext = path.extname(file);
    if (!TEXT_EXT.has(ext) && !path.basename(file).startsWith(".env")) continue;

    const isSelf = SELF.some((p) => file.startsWith(p));
    const brandScope =
      !isSelf && file.startsWith(WEB) && BRAND_EXT.has(ext) && !file.startsWith(TOKENS) && !file.startsWith(NEUTRAL_TOKENS);
    const urlScope = !isSelf;
    if (!brandScope && !urlScope) continue;

    const lines = readFileSync(abs, "utf8").split(/\r?\n/);
    lines.forEach((text, index) => {
      const report = (rule) => violations.push({ file, line: index + 1, rule });
      if (brandScope) {
        if (HEX.test(text) || COLOR_FN.test(text)) report("brand-literal: color value outside src/tokens");
        if (FONT_FAMILY.test(text)) report("brand-literal: font family outside src/tokens");
        for (const match of text.matchAll(IMPORT_SPECIFIER)) {
          if (TOKENS_INTERNAL.test(match[1])) report(`tokens-internal: import "${match[1]}" (use the tokens entry point)`);
        }
      }
      if (urlScope && API_BASE_URL.test(text)) report("api-base-url: the SPA must not define or read an API base URL");
    });
  }
  return violations;
}
