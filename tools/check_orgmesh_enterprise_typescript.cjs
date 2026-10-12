// SPDX-License-Identifier: MIT
// Parse executable imports. Comments and string prose are not dependency edges.
const fs = require("node:fs");
const path = require("node:path");
const { createRequire } = require("node:module");
const root = process.argv[2];
const swc = createRequire(path.join(root, "web/package.json"))("@swc/core");
const input = JSON.parse(fs.readFileSync(0, "utf8"));
const dependencies = new Set();
const failures = [];
function dependency(value, location) {
  if (typeof value !== "string") {
    failures.push(`${location}: unresolved executable import`);
    return;
  }
  dependencies.add(value);
  if (value.split(/[/.]/).includes("ee")) {
    failures.push(`${location}: forbidden dependency ${value}`);
  }
}
function visit(node) {
  if (!node || typeof node !== "object") return;
  if (
    node.type === "TsImportEqualsDeclaration" &&
    node.moduleRef?.type !== "TsExternalModuleReference"
  ) {
    dependency(undefined, "import-equals");
  }
  if (node.type === "TsExternalModuleReference") {
    const expression = node.expression;
    dependency(
      expression?.type === "StringLiteral" ? expression.value : undefined,
      "import-equals"
    );
  }
  if (
    node.type === "VariableDeclarator" &&
    node.init?.type === "Identifier" &&
    node.init.value === "require"
  ) {
    failures.push("indirect executable loader alias");
  }
  if (
    (node.type === "CallExpression" || node.type === "NewExpression") &&
    node.callee.type === "Identifier" &&
    ["eval", "Function"].includes(node.callee.value)
  ) {
    failures.push("executable code generation is unsupported");
  }
  if (
    [
      "ImportDeclaration",
      "ExportAllDeclaration",
      "ExportNamedDeclaration",
    ].includes(node.type) &&
    node.source
  ) {
    dependency(node.source.value, node.type);
  }
  if (
    node.type === "CallExpression" &&
    (node.callee.type === "Import" ||
      (node.callee.type === "Identifier" && node.callee.value === "require"))
  ) {
    const argument = node.arguments[0]?.expression;
    dependency(
      argument?.type === "StringLiteral" ? argument.value : undefined,
      "dynamic import"
    );
  }
  for (const value of Object.values(node)) {
    if (Array.isArray(value)) value.forEach(visit);
    else if (value && typeof value === "object") visit(value);
  }
}
try {
  visit(
    swc.parseSync(input.source, {
      syntax: "typescript",
      tsx: input.file.endsWith(".tsx"),
    })
  );
} catch (error) {
  failures.push(`syntax parse failed: ${error.message}`);
}
process.stdout.write(
  JSON.stringify({
    file: input.file,
    dependencies: [...dependencies].sort(),
    failures,
  })
);
