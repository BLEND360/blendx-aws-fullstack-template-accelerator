import { readBootConfig } from "./env";

const full = {
  VITE_COGNITO_REGION: "us-east-1",
  VITE_COGNITO_USER_POOL_ID: "us-east-1_abc",
  VITE_COGNITO_APP_CLIENT_ID: "client",
  VITE_COGNITO_DOMAIN: "auth.example.test",
};

test("with the three Cognito values present the app requires sign-in", () => {
  const config = readBootConfig(full);
  expect(config.isLocalMode).toBe(false);
  expect(config.cognito).toEqual({
    region: "us-east-1",
    userPoolId: "us-east-1_abc",
    appClientId: "client",
    domain: "auth.example.test",
  });
});

test.each(["VITE_COGNITO_USER_POOL_ID", "VITE_COGNITO_APP_CLIENT_ID", "VITE_COGNITO_DOMAIN"])(
  "without %s the app runs in local mode",
  (missing) => {
    expect(readBootConfig({ ...full, [missing]: "" }).isLocalMode).toBe(true);
  },
);

test("an empty environment is local mode", () => {
  expect(readBootConfig({}).isLocalMode).toBe(true);
});

test("the environment type declares no API base URL", () => {
  expect(Object.keys(readBootConfig(full))).toEqual(["cognito", "isLocalMode"]);
});
