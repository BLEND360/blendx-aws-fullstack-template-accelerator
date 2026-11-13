/** A post-sign-in destination is trusted only if it is a path on this origin:
 * "/x" is, "//evil.test" and "/\evil.test" are not (browsers read both as another host). */
export function safeReturnTo(value: unknown): string {
  return typeof value === "string" && /^\/(?![/\\])/.test(value) ? value : "/";
}
