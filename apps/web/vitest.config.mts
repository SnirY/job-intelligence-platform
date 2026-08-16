import react from "@vitejs/plugin-react";
import tsconfigPaths from "vite-tsconfig-paths";
import { defineConfig } from "vitest/config";

// .mts, not .ts: the app is CommonJS by default, and vitest would try to
// require() this file's ESM-only plugin dependencies.
export default defineConfig({
  plugins: [tsconfigPaths(), react()],
  test: {
    environment: "jsdom",
    globals: true,
    // DEV-058. A parallel run spends more time building test environments than
    // running tests — 65-73s of jsdom setup against ~3s of assertions on this
    // suite. That is the number to watch when the suite next fails under load,
    // and without it a failure report says only "timed out".
    logHeapUsage: true,
    setupFiles: ["./vitest.setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
