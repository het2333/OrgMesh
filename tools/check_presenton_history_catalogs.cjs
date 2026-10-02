/** Verify new history keys and ICU arguments across every existing locale. */
const fs = require("node:fs");
const path = require("node:path");
const { parse } = require("@formatjs/icu-messageformat-parser");
const root = path.resolve(__dirname, "../web/src/i18n/messages");
function flatten(value, prefix = "") {
  return Object.fromEntries(Object.entries(value).flatMap(([key, item]) => {
    const name = prefix ? `${prefix}.${key}` : key;
    return typeof item === "string" ? [[name, item]] : Object.entries(flatten(item, name));
  }));
}
function args(elements) {
  return elements.flatMap((item) => {
    const own = item.type >= 1 && item.type <= 6 ? [`${item.type}:${item.value}`] : [];
    const nested = item.options ? Object.values(item.options).flatMap((option) => args(option.value)) : item.children ? args(item.children) : [];
    return [...own, ...nested];
  }).sort();
}
const catalogs = fs.readdirSync(root).filter((name) => name.endsWith(".json"));
const source = flatten(JSON.parse(fs.readFileSync(path.join(root, "en.json"))).workspace.tools.history);
for (const name of catalogs) {
  const target = flatten(JSON.parse(fs.readFileSync(path.join(root, name))).workspace.tools.history);
  if (JSON.stringify(Object.keys(source).sort()) !== JSON.stringify(Object.keys(target).sort())) throw new Error(`${name}: history key mismatch`);
  for (const [key, value] of Object.entries(source)) {
    if (JSON.stringify(args(parse(value))) !== JSON.stringify(args(parse(target[key])))) throw new Error(`${name}: ICU arguments differ at ${key}`);
  }
}
console.log(`${catalogs.length} locale catalogs: ${Object.keys(source).length} history keys and ICU arguments match`);
