import path from "node:path";
import { fileURLToPath } from "node:url";
import { scan } from "./boundaries.mjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");
const violations = scan(root);
for (const v of violations) console.error(`${v.file}:${v.line}  ${v.rule}`);
if (violations.length) {
  console.error(`\n${violations.length} boundary violation(s).`);
  process.exit(1);
}
console.log("Boundaries OK.");
