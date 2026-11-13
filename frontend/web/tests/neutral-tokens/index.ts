/** A brandless replacement for src/tokens: antd's default light and dark themes,
 * no logo, no fonts. `npm run test:neutral` swaps it in for src/tokens/index.ts
 * and runs the whole suite, which is the proof that replacing the folder (same
 * entry point, same exports) leaves the app compiling and working, with no
 * trace of Blend. Start from this file when adopting another brand. */
import { theme } from "antd";
import { Fragment, createElement } from "react";
import type { ThemeConfig } from "antd";
import type * as Brand from "../../src/tokens";

export const lightTheme: ThemeConfig = { algorithm: theme.defaultAlgorithm };
export const darkTheme: ThemeConfig = { algorithm: theme.darkAlgorithm };

export function BrandLogo(_props: Brand.BrandLogoProps) {
  return createElement(Fragment);
}

export function applyBrandDocument(): void {}

// Fails to compile if the real entry point gains or changes an export this file lacks.
export const contract = { lightTheme, darkTheme, BrandLogo, applyBrandDocument } satisfies typeof Brand;
export type BrandLogoProps = Brand.BrandLogoProps;
