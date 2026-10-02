/** Verify Word labels and ICU parameters across supported locales. */
const fs = require("node:fs");
const path = require("node:path");
const { parse } = require("@formatjs/icu-messageformat-parser");
const root = path.resolve(__dirname, "../web/src/i18n/messages");
const catalogs = fs.readdirSync(root).filter((file) => file.endsWith(".json"));
const source = JSON.parse(fs.readFileSync(path.join(root, "en.json"))).workspace.tools.word;
function argumentsOf(elements) {
  return elements.flatMap((element) => [
    ...(element.type >= 1 && element.type <= 6 ? [`${element.type}:${element.value}`] : []),
    ...(element.options ? Object.values(element.options).flatMap((option) => argumentsOf(option.value)) : []),
    ...(element.children ? argumentsOf(element.children) : []),
  ]).sort();
}
for (const locale of catalogs) {
  const target = JSON.parse(fs.readFileSync(path.join(root, locale))).workspace.tools.word;
  if (JSON.stringify(Object.keys(source).sort()) !== JSON.stringify(Object.keys(target).sort())) throw new Error(`${locale}: Word key mismatch`);
  for (const key of Object.keys(source)) {
    if (JSON.stringify(argumentsOf(parse(source[key]))) !== JSON.stringify(argumentsOf(parse(target[key])))) throw new Error(`${locale}: ICU mismatch at ${key}`);
  }
}
console.log(`${catalogs.length} locale catalogs: ${Object.keys(source).length} Word keys and ICU arguments match`);
