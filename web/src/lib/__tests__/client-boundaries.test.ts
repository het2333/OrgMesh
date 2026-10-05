import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { loadBindings, transform } from "next/dist/build/swc";

beforeAll(async () => {
  await loadBindings();
});

test.each([
  "lib/opal/src/components/inputs/chrono/input-date-range-picker/components.tsx",
  "lib/opal/src/layouts/toast/store.ts",
])(
  "a server import preserves the client boundary for %s",
  async (relativePath) => {
    const filename = resolve(relativePath);
    const result = await transform(readFileSync(filename, "utf8"), {
      filename,
      jsc: { parser: { syntax: "typescript", tsx: filename.endsWith(".tsx") } },
      serverComponents: {
        isReactServerLayer: true,
        cacheComponentsEnabled: false,
        useCacheEnabled: false,
        taintEnabled: false,
        pageExtensions: ["tsx", "ts"],
      },
    });
    expect(result.code).toContain("__next_internal_client_entry_do_not_use__");
  }
);
