/** Focused UI tests. Real React/JSDOM; Opal and application boundaries are mocks. */
const path = require("node:path");
const { runCLI } = require("jest");
const root = path.resolve(__dirname, "../web");
const modules = process.env.ORGMESH_TEST_NODE_MODULES;
if (!modules) throw new Error("Set ORGMESH_TEST_NODE_MODULES to the test dependency directory");
const config = {
  rootDir: root,
  testEnvironment: path.join(modules, "jest-environment-jsdom"),
  moduleDirectories: ["node_modules", modules],
  moduleNameMapper: { "^@/(.*)$": "<rootDir>/src/$1", "^@opal/(.*)$": "<rootDir>/lib/opal/src/$1" },
  transform: { "^.+\\.(t|j)sx?$": [path.join(modules, "@swc/jest"), { jsc: { parser: { syntax: "typescript", tsx: true }, transform: { react: { runtime: "automatic" } }, target: "es2022" }, module: { type: "commonjs" } }] },
  testMatch: ["**/src/sections/workspace/presentations/history.test.ts", "**/src/sections/workspace/presentations/PresentationHistory.test.tsx"],
  maxWorkers: 1,
  clearMocks: true,
};
runCLI({ config: JSON.stringify(config), runInBand: true }, [root]).then(({ results }) => { process.exitCode = results.success ? 0 : 1; });
