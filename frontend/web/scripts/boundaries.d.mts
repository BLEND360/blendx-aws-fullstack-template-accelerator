export interface Violation {
  file: string;
  line: number;
  rule: string;
}
export function scan(root: string): Violation[];
