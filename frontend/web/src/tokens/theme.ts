/**
 * Blend brand themes for antd's `ConfigProvider`: `lightTheme` and `darkTheme`.
 * Built on antd's default and dark algorithms so derived tokens (hover, active,
 * link) come from the algorithm rather than hand-tuned values. This file and
 * the rest of `src/tokens/` are the only place brand values may live.
 */

import { theme, type ThemeConfig } from "antd";
import { fontFamily } from "./typography";

// ─── Shared component overrides ──────────────────────────────────────────────
// Applied to both light and dark themes. Dark adds `Button.solidTextColor` on top.

const sharedComponents: NonNullable<ThemeConfig["components"]> = {
  Button: {
    fontWeight: 500,
    paddingInline: 14,
    paddingInlineLG: 16,
    primaryShadow: "0 2px 0 rgba(5,48,87,0.1)",
  },
  Input: {
    activeShadow: "0 0 0 2px rgba(5,48,87,0.1)",
    errorActiveShadow: "0 0 0 2px rgba(192,48,45,0.1)",
    warningActiveShadow: "0 0 0 2px rgba(192,138,15,0.1)",
  },
};

// Light-mode form input chrome — cool-gray border and placeholder so inputs
// read as cooler/cleaner against the white app surface (the AntD default
// `#d9d9d9` border and 25% black placeholder are warm neutrals). Scoped per
// form-component so non-input surfaces are untouched.
const lightInputBorder = "#9CA3AF";
const lightInputPlaceholder = "#9CA3AF";

// ─── Light theme ─────────────────────────────────────────────────────────────

export const lightTheme: ThemeConfig = {
  algorithm: theme.defaultAlgorithm,
  token: {
    colorPrimary: "#053057",
    colorSuccess: "#109b48",
    colorWarning: "#c08a0f",
    colorError: "#c0302d",
    colorInfo: "#314550",
    // colorTextBase remains navy so AntD derives heading/title colors from brand;
    // body paragraph and secondary text are explicitly overridden to dark grays
    // below to give content a more neutral, readable tone.
    colorTextBase: "#053057",
    colorText: "#4a4a4a",
    colorTextSecondary: "#737373",
    // `<Typography type="secondary">` reads `colorTextDescription`, not
    // `colorTextSecondary` — keep both aligned so secondary copy renders gray.
    colorTextDescription: "#737373",
    colorBgBase: "#ffffff",
    fontFamily: fontFamily.sans,
    fontSize: 16,
    borderRadius: 8,
  },
  components: {
    ...sharedComponents,
    Input: {
      ...sharedComponents.Input,
      colorBorder: lightInputBorder,
      colorTextPlaceholder: lightInputPlaceholder,
    },
    InputNumber: {
      colorBorder: lightInputBorder,
      colorTextPlaceholder: lightInputPlaceholder,
    },
    Select: {
      colorBorder: lightInputBorder,
      colorTextPlaceholder: lightInputPlaceholder,
    },
    DatePicker: {
      colorBorder: lightInputBorder,
      colorTextPlaceholder: lightInputPlaceholder,
    },
    Mentions: {
      colorBorder: lightInputBorder,
      colorTextPlaceholder: lightInputPlaceholder,
    },
    Cascader: {
      colorBorder: lightInputBorder,
      colorTextPlaceholder: lightInputPlaceholder,
    },
    TreeSelect: {
      colorBorder: lightInputBorder,
      colorTextPlaceholder: lightInputPlaceholder,
    },
    Radio: {
      colorBorder: lightInputBorder,
    },
    Checkbox: {
      colorBorder: lightInputBorder,
    },
    Tooltip: {
      // Invert AntD's default dark-spotlight tooltip — off-white bg with dark
      // gray body-text color so tooltips read as light surfaces in light mode.
      colorBgSpotlight: "#f4f3f0",
      colorTextLightSolid: "#4a4a4a",
    },
    Segmented: {
      // Active segment renders as full brand navy (`--color-brand-500`) with
      // white text so the selected pill carries the same brand presence as
      // primary buttons rather than fading into the track bg. Inactive
      // segments use navy text so they clear WCAG AA on the light track bg
      // (AntD's default gray text lands well under 4.5:1).
      itemSelectedBg: "#053057",
      itemSelectedColor: "#ffffff",
      itemColor: "#053057",
      itemHoverColor: "#053057",
    },
    Menu: {
      // Active (selected) menu item — navy bg + white text. White on
      // `#053057` clears WCAG AA easily (~15:1). AntD's default pairs a pale
      // tint bg with brand-colored text and lands well under AA on the small
      // text size used in menu items.
      itemSelectedBg: "#053057",
      itemSelectedColor: "#ffffff",
    },
    Table: {
      // Header row uses full brand navy (`--color-brand-500`) with white text
      // so it reads as a branded band against the white app surface. Sort
      // active/hover bgs lift one step (`#0a3f6e`) instead of darkening —
      // there's no room below navy to keep the affordance visible.
      headerBg: "#053057",
      headerColor: "#ffffff",
      headerSortActiveBg: "#0a3f6e",
      headerSortHoverBg: "#0a3f6e",
      rowHoverBg: "#f4f3f0",
      // Square corners — opt out of the global 8px borderRadius for tables.
      borderRadius: 0,
      borderRadiusLG: 0,
      headerBorderRadius: 0,
    },
  },
};

// ─── Dark theme ──────────────────────────────────────────────────────────────

export const darkTheme: ThemeConfig = {
  algorithm: theme.darkAlgorithm,
  token: {
    // Seed tokens
    colorPrimary: "#A2F3F3",
    colorSuccess: "#109b48",
    colorWarning: "#c08a0f",
    colorError: "#c0302d",
    colorInfo: "#314550",
    colorTextBase: "#f4f3f0",
    colorBgBase: "#0b0d0e",
    fontFamily: fontFamily.sans,
    fontSize: 16,
    borderRadius: 8,

    // Map overrides — bypass darkAlgorithm derivations for these specific tokens
    colorBgContainer: "#1a1f24",
    colorBgElevated: "#242c32",
    colorText: "#f4f3f0",
    colorTextSecondary: "#A2F3F3",
    colorTextTertiary: "#6abfbf",
    colorTextQuaternary: "#3d8f8f",
    colorTextPlaceholder: "#f4f3f0",
    colorFill: "#1a1f24",
    colorFillSecondary: "#141a1e",
    colorFillTertiary: "#0f1418",
    colorFillQuaternary: "#0b0d0e",
    colorBorder: "#615e58",
    // Text color on solid/primary buttons (and other "filled" surfaces). AntD's
    // darkAlgorithm derives this as white by default; the cyan dark primary needs
    // near-black for legible contrast on solid buttons.
    colorTextLightSolid: "#0b0d0e",
    // Link triplet tracks the primary chain: setting colorLink seeds it and the
    // darkAlgorithm derives colorLinkHover / colorLinkActive automatically, so
    // they end up equal to colorPrimaryHover / colorPrimaryActive (spec intent).
    colorLink: "#A2F3F3",
  },
  components: {
    ...sharedComponents,
    Button: {
      ...sharedComponents.Button,
      // Text on the cyan primary solid button — near-black for legibility.
      solidTextColor: "#0b0d0e",
      // Danger buttons render on the deep-red `colorError` bg; near-black text
      // fails WCAG contrast there. Use white to clear AA contrast minimums.
      dangerColor: "#ffffff",
    },
    Table: {
      headerBg: "#A2F3F3",
      headerColor: "#0b0d0e",
      headerSortActiveBg: "#8ddede",
      headerSortHoverBg: "#8ddede",
      rowHoverBg: "#1a1f24",
      // Square corners — opt out of the global 8px borderRadius for tables.
      borderRadius: 0,
      borderRadiusLG: 0,
      headerBorderRadius: 0,
    },
    Menu: {
      darkItemBg: "#141a1e",
      darkPopupBg: "#141a1e",
      darkSubMenuItemBg: "#0b0d0e",
      darkItemColor: "#f4f3f0",
      darkItemHoverColor: "#A2F3F3",
      darkGroupTitleColor: "#A2F3F3",
      darkItemDisabledColor: "#3d8f8f",
      // Active (selected) item — near-black text + icon on the turquoise
      // selected bg. Icons inherit `darkItemSelectedColor`.
      darkItemSelectedColor: "#0b0d0e",
    },
    Layout: {
      headerBg: "#141a1e",
      siderBg: "#141a1e",
      triggerBg: "#1a1f24",
    },
    Tooltip: {
      // Global colorTextLightSolid is near-black so solid primary buttons stay
      // legible on cyan; tooltips render on the dark spotlight bg and need
      // off-white text instead.
      colorTextLightSolid: "#f4f3f0",
    },
    Pagination: {
      // darkAlgorithm leaves pagination item bgs near-white; pin them to the
      // dark container surface so the strip matches the rest of the table.
      itemBg: "#1a1f24",
      itemLinkBg: "#1a1f24",
      itemInputBg: "#1a1f24",
      itemActiveBg: "#1a1f24",
    },
    Progress: {
      // Default (non-status) Progress stroke — AntD uses colorInfo here, which
      // is the dark slate `#314550` and reads as flat gray on dark surfaces.
      // Pin to the dark-mode cyan so the bar matches brand. `success` and
      // `exception` variants still derive from colorSuccess/colorError.
      defaultColor: "#A2F3F3",
    },
  },
};
