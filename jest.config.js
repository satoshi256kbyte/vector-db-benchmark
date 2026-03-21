module.exports = {
  testEnvironment: "node",
  roots: ["<rootDir>/test"],
  testMatch: ["**/*.test.ts"],
  transform: {
    "^.+\\.tsx?$": "ts-jest",
  },
  globalSetup: "<rootDir>/test/setup-sam-mock.ts",
  globalTeardown: "<rootDir>/test/teardown-sam-mock.ts",
};
