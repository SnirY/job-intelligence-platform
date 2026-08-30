import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // @jip/shared-types ships TypeScript source rather than a build artifact, so
  // Next compiles it as part of the app.
  transpilePackages: ["@jip/shared-types"],
  // The workspace root holds Python packages too; scope file tracing to the app
  // so `next build` does not walk the whole monorepo.
  outputFileTracingRoot: __dirname,
  // Two `next dev` processes on one project share `.next` and corrupt each
  // other's cache — the second server never finishes starting and the first
  // starts answering 500. That is not hypothetical: it happened while
  // verifying local auth mode side by side with a Clerk-mode server.
  //
  // Setting NEXT_DIST_DIR gives a second server its own build directory, which
  // is what makes running both modes at once possible. Unset, this is exactly
  // the default.
  distDir: process.env.NEXT_DIST_DIR ?? ".next",
};

export default nextConfig;
