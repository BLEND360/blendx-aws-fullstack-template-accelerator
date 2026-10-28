/** A brandless stand-in for src/tokens (antd defaults, no logo or fonts); `npm run test:neutral` runs the suite against it. */
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
