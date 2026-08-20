import { cpus } from "node:os";

import react from "@vitejs/plugin-react";
import tsconfigPaths from "vite-tsconfig-paths";
import { defineConfig } from "vitest/config";

/**
 * Half the cores, never fewer than one.
 *
 * DEV-069. Vitest defaults to one worker per core less one, and every worker
 * here builds a jsdom. On the eight-core machine this was measured on that put
 * seven CPU-bound workers against eight cores with a Docker stack already
 * running, and the suite did not degrade gracefully — it thrashed. Measured
 * against six spinners for competition:
 *
 *   default (7 workers)  134.4s wall, slowest test 5440ms, three tests failed
 *   half the cores (4)    66.4s wall, slowest test 4323ms, none failed
 *
 * Oversubscription was making the run twice as slow, not faster, and the
 * failures were its symptom rather than a separate problem. On a quiet machine
 * the two are within noise of each other (30-36s either way), so this costs
 * nothing and removes the dependency on the machine being idle — which is the
 * property that matters, because nobody checks whether it is.
 */
const WORKERS = Math.max(1, Math.floor(cpus().length / 2));

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
    /**
     * Margin, not the repair.
     *
     * The worker bound above is what stopped the failures; this is the room
     * left over for a machine busier than the one it was measured on. The
     * slowest test under deliberate competition was 4323ms against vitest's
     * default ceiling of 5000ms — 86% of it, which is not a margin. Fifteen
     * seconds is roughly three and a half times the adversarial peak.
     *
     * Raising this on its own would have been the wrong repair and is worth
     * saying out loud: a suite that stops going red because the ceiling moved
     * still has whatever made it slow, and has lost the signal that said so.
     */
    testTimeout: 15_000,
    poolOptions: { threads: { maxThreads: WORKERS, minThreads: 1 } },
    setupFiles: ["./vitest.setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
