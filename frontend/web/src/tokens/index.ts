/** The only public entry of the brand; `tests/neutral-tokens` declares the same contract. */
import "@fontsource-variable/montserrat";
import "./global.css";
import faviconUrl from "./assets/blend-symbol-ink.svg";

export { lightTheme, darkTheme } from "./theme";
export { BrandLogo } from "./BrandLogo";
export type { BrandLogoProps } from "./BrandLogo";

/** Puts the brand's document-level metadata (favicon) in place. Idempotent. */
export function applyBrandDocument(): void {
  let link = document.querySelector<HTMLLinkElement>("link[rel~='icon']");
  if (!link) {
    link = document.createElement("link");
    link.rel = "icon";
    document.head.appendChild(link);
  }
  link.type = "image/svg+xml";
  link.href = faviconUrl;
}
