import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { scan } from "../scripts/boundaries.mjs";

// Built from pieces so this file does not trip the rules it tests.
const HEX = "#" + "12ab34";
const RGBA = "rgb" + "a(0,0,0,0.5)";
const BASE_URL = "API" + "_BASE_URL";

let root: string;
beforeEach(() => {
  root = mkdtempSync(path.join(os.tmpdir(), "boundaries-"));
});
afterEach(() => rmSync(root, { recursive: true, force: true }));

function put(rel: string, content: string) {
  const abs = path.join(root, rel);
  mkdirSync(path.dirname(abs), { recursive: true });
  writeFileSync(abs, content);
}

test("a clean tree has no violations", () => {
  put("frontend/web/src/App.tsx", `import { lightTheme } from "../tokens";\nconst x = 1;\n`);
  put("frontend/web/src/tokens/theme.ts", `export const p = "${HEX}";\n`);
  expect(scan(root)).toEqual([]);
});

test.each([
  ["hex color", `const c = "${HEX}";`],
  ["color function", `const c = "${RGBA}";`],
  ["css font family", `body { font-family: Arial, sans-serif; }`],
  ["literal fontFamily", `const s = { fontFamily: "Arial" };`],
])("%s outside tokens names the file and line", (_label, line) => {
  const ext = line.includes("{ font-family") || line.startsWith("body") ? "css" : "ts";
  put(`frontend/web/src/pages/Page.${ext}`, `\n${line}\n`);
  const [violation, ...rest] = scan(root);
  expect(rest).toEqual([]);
  expect(violation).toMatchObject({ file: `frontend/web/src/pages/Page.${ext}`, line: 2 });
  expect(violation.rule).toMatch(/^brand-literal/);
});

test("reading the theme's font family is allowed", () => {
  put("frontend/web/src/App.tsx", `const s = { fontFamily: token.fontFamily };\n`);
  expect(scan(root)).toEqual([]);
});

test.each([
  `import { lightTheme } from "../tokens/theme";`,
  `import "../tokens/global.css";`,
  `export { x } from "./tokens/index";`,
  `const m = await import("../../tokens/typography");`,
])("an import of a tokens internal file is flagged: %s", (line) => {
  put("frontend/web/src/App.tsx", `${line}\n`);
  expect(scan(root).map((v) => v.rule)).toEqual([expect.stringMatching(/^tokens-internal/)]);
});

test("css url() into tokens internals is flagged", () => {
  put("frontend/web/src/a.css", `.x { background: url("../tokens/assets/logo.svg"); }\n`);
  expect(scan(root).map((v) => v.rule)).toEqual([expect.stringMatching(/^tokens-internal/)]);
});

test("the neutral replacement and src/tokens may hold brand values", () => {
  put("frontend/web/tests/neutral-tokens/index.ts", `export const c = "${HEX}";\n`);
  put("frontend/web/src/tokens/global.css", `a { color: ${HEX}; }\n`);
  expect(scan(root)).toEqual([]);
});

test("an API base URL anywhere in the repository is flagged, lock files and specs are not", () => {
  put("frontend/web/.env", `VITE_${BASE_URL}=http://localhost:8000\n`);
  put("backend/api/app/x.py", `url = os.environ["${BASE_URL}"]\n`);
  put("frontend/web/package-lock.json", `"${BASE_URL}"\n`);
  put(".kiro/specs/s/requirements.md", `${BASE_URL}\n`);
  put("frontend/web/scripts/boundaries.mjs", `${BASE_URL}\n`);
  expect(scan(root).map((v) => v.file).sort()).toEqual(["backend/api/app/x.py", "frontend/web/.env"]);
});
