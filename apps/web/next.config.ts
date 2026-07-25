import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // @jip/shared-types ships TypeScript source rather than a build artifact, so
  // Next compiles it as part of the app.
  transpilePackages: ["@jip/shared-types"],
  // The workspace root holds Python packages too; scope file tracing to the app
  // so `next build` does not walk the whole monorepo.
  outputFileTracingRoot: __dirname,
};

export default nextConfig;
