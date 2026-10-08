import inkUrl from "./assets/blend-symbol-ink.svg";
import paperUrl from "./assets/blend-symbol-paper.svg";

export interface BrandLogoProps {
  height?: number;
  /** The symbol comes in an ink and a paper variant; pick the one that reads on the active mode. */
  mode?: "light" | "dark";
}

export function BrandLogo({ height = 32, mode = "light" }: BrandLogoProps) {
  return <img src={mode === "dark" ? paperUrl : inkUrl} height={height} alt="" />;
}
