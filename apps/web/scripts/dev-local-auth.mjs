/**
 * Run a second dev server in local authentication mode, beside the usual one.
 *
 *   npm run dev:local-auth --workspace @jip/web
 *
 * Exists because inline environment variables (`FOO=bar npm run dev`) are a
 * POSIX shell feature and this project is developed on Windows, where that line
 * is a syntax error rather than a warning. A fifteen-line script beats adding
 * cross-env for one command.
 *
 * The separate `NEXT_DIST_DIR` is not optional. Two `next dev` processes
 * sharing `.next` corrupt each other's cache: the second never finishes
 * starting and the first begins answering 500.
 *
 * The secret here is a development placeholder and is meant to be visible. It
 * has to match the API's `JIP_AUTH_LOCAL_SECRET` for a request to get past
 * authentication — see `.env.example`.
 */

import { spawn } from "node:child_process";

const PORT = process.env.PORT ?? "3001";

const child = spawn("npx", ["next", "dev", "--port", PORT], {
  stdio: "inherit",
  shell: true,
  env: {
    ...process.env,
    NEXT_PUBLIC_AUTH_PROVIDER: "local",
    AUTH_LOCAL_SECRET: process.env.AUTH_LOCAL_SECRET ?? "local-demo-secret-for-development-only",
    NEXT_DIST_DIR: ".next-local-auth",
  },
});

child.on("exit", (code) => process.exit(code ?? 0));
