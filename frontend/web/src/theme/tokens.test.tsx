import { render } from "@testing-library/react";
import { theme, type ThemeConfig } from "antd";
import { BrandLogo, applyBrandDocument, darkTheme, lightTheme } from "../tokens";

// WCAG 2.1 relative luminance and contrast ratio.
function luminance(color: string): number {
  // antd emits both #rgb and #rrggbb.
  const hex = color.length === 4 ? `#${[...color.slice(1)].map((c) => c + c).join("")}` : color;
  const [r, g, b] = [1, 3, 5].map((i) => {
    const c = parseInt(hex.slice(i, i + 2), 16) / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

const themes: [string, ThemeConfig][] = [
  ["light", lightTheme],
  ["dark", darkTheme],
];

describe.each(themes)("%s theme", (_name, config) => {
  const t = theme.getDesignToken(config);

  test.each([
    ["body text", t.colorText, t.colorBgContainer],
    ["secondary text", t.colorTextSecondary, t.colorBgContainer],
    ["description text", t.colorTextDescription, t.colorBgContainer],
    ["links", t.colorLink, t.colorBgContainer],
    ["primary on page", t.colorPrimary, t.colorBgBase],
    ["text on a solid primary button", t.colorTextLightSolid, t.colorPrimary],
  ])("%s meets WCAG AA (4.5:1)", (_label, foreground, background) => {
    expect(contrast(foreground, background)).toBeGreaterThanOrEqual(4.5);
  });
});

test("both modes are complete antd themes", () => {
  expect(lightTheme.algorithm).toBeDefined();
  expect(darkTheme.algorithm).toBeDefined();
  expect(lightTheme.algorithm).not.toBe(darkTheme.algorithm);
});

test("the logo has a variant for each mode", () => {
  const light = render(<BrandLogo mode="light" />).container.querySelector("img")!.src;
  const dark = render(<BrandLogo mode="dark" />).container.querySelector("img")!.src;
  expect(light).not.toBe(dark);
});

test("applyBrandDocument sets one favicon and is idempotent", () => {
  applyBrandDocument();
  applyBrandDocument();
  expect(document.querySelectorAll("link[rel~='icon']")).toHaveLength(1);
  expect(document.querySelector<HTMLLinkElement>("link[rel~='icon']")!.href).not.toBe("");
});
