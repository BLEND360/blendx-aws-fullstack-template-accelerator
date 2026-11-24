import { turnErrorFallback, turnErrorMessage, turnErrorMessages } from "./messages";

test("every known error code has its own fixed sentence", () => {
  for (const code of Object.keys(turnErrorMessages)) {
    expect(turnErrorMessage(code)).toBe(turnErrorMessages[code]);
    expect(turnErrorMessage(code)).not.toContain(code); // never the raw code
  }
});

test("an unknown code gets the default sentence, whatever it says", () => {
  expect(turnErrorMessage("arn:aws:iam::123456789012:role/secret")).toBe(turnErrorFallback);
  expect(turnErrorMessage("")).toBe(turnErrorFallback);
  expect(turnErrorMessage("constructor")).toBe(turnErrorFallback); // not an inherited property
  expect(turnErrorFallback).not.toMatch(/arn:|_/);
});
