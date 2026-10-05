import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import * as path from "node:path";
import { dirname, resolve } from "node:path";
import { runInNewContext } from "node:vm";

interface SentryBuildOptions {
  telemetry?: boolean;
  sourcemaps?: { disable?: boolean };
  release?: { create?: boolean; finalize?: boolean };
  webpack?: { unstable_sentryWebpackPluginOptions?: { disable?: boolean } };
}

function configure(env: Record<string, string> = {}) {
  const calls: SentryBuildOptions[] = [];
  const configModule = { exports: (_phase: string): unknown => undefined };
  runInNewContext(readFileSync(resolve("next.config.js"), "utf8"), {
    module: configModule,
    __dirname: process.cwd(),
    process: { env },
    require: (name: string) => {
      if (name === "@sentry/nextjs") {
        return {
          withSentryConfig: (config: unknown, options: SentryBuildOptions) => {
            calls.push(options);
            return config;
          },
        };
      }
      if (name === "next/constants") {
        return { PHASE_DEVELOPMENT_SERVER: "phase-development-server" };
      }
      if (name === "next-intl/plugin") {
        return () => (config: unknown) => config;
      }
      throw new Error(`Unexpected config dependency: ${name}`);
    },
  });
  configModule.exports("phase-production-build");
  return calls;
}

test("an unconfigured build does not apply the Sentry build plugin", () => {
  expect(configure()).toHaveLength(0);
});

test("a configured build disables Sentry telemetry, uploads and release writes", () => {
  const calls = configure({
    SENTRY_AUTH_TOKEN: "test-only",
    NEXT_PUBLIC_SENTRY_DSN: "https://example.test",
  });
  expect(calls).toHaveLength(1);
  expect(calls[0]?.telemetry).toBe(false);
  expect(calls[0]?.sourcemaps?.disable).toBe(true);
  expect(calls[0]?.release?.create).toBe(false);
  expect(calls[0]?.release?.finalize).toBe(false);
});

const buildTools = [
  "webpack-nodejs",
  "webpack-edge",
  "webpack-client",
  "after-production-compile-webpack",
  "after-production-compile-turbopack",
];
const releaseCases = [
  { releaseName: undefined, env: {} },
  { releaseName: "test-only", env: {} },
  {
    releaseName: undefined,
    env: { VERCEL: "1", VERCEL_TARGET_ENV: "preview" },
  },
  {
    releaseName: "test-only",
    env: { VERCEL: "1", VERCEL_TARGET_ENV: "preview" },
  },
];

test.each(
  buildTools.flatMap((buildTool) =>
    releaseCases.map((scenario) => ({ buildTool, ...scenario }))
  )
)(
  "the installed Sentry adapter disables $buildTool with release $releaseName and env $env",
  ({ buildTool, releaseName, env }) => {
    const [options] = configure({
      SENTRY_AUTH_TOKEN: "test-only",
      NEXT_PUBLIC_SENTRY_DSN: "https://example.test",
    });
    const nextPath = require.resolve("@sentry/nextjs");
    const buildExports: Record<string, unknown> = {};
    // This installed adapter imports only node:path. Never load SDK/CLI hooks.
    runInNewContext(
      readFileSync(
        resolve(dirname(nextPath), "config/getBuildPluginOptions.js"),
        "utf8"
      ),
      {
        exports: buildExports,
        require: (name: string) => {
          if (name === "path") return path;
          throw new Error(`Unexpected build adapter dependency: ${name}`);
        },
      }
    );
    const mapOptions = buildExports.getBuildPluginOptions;
    if (typeof mapOptions !== "function")
      throw new Error("Missing Sentry build adapter");
    const mapped: unknown = mapOptions({
      sentryBuildOptions: options,
      releaseName,
      buildTool,
      distDirAbsPath: "/test-only/.next",
      useRunAfterProductionCompileHook: true,
    });

    const webpackPath = createRequire(nextPath).resolve(
      "@sentry/webpack-plugin"
    );
    const corePath = createRequire(webpackPath).resolve(
      "@sentry/bundler-plugin-core"
    );
    const source = readFileSync(corePath, "utf8");
    const start = source.indexOf(
      "function normalizeUserOptions(userOptions) {"
    );
    const end = source.indexOf("\n/**", start);
    if (start < 0 || end < 0)
      throw new Error("Missing Sentry option normalizer");
    // Run only pure option normalization, with synthetic environment/release data.
    const normalized: unknown = runInNewContext(
      `${source.slice(start, end)}\nnormalizeUserOptions(inputOptions)`,
      {
        inputOptions: mapped,
        process: { env },
        determineReleaseName: () => "test-only",
      }
    );
    expect(normalized).toEqual(
      expect.objectContaining({ disable: true, telemetry: false })
    );
  }
);
