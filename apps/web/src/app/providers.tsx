"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ThemeProvider } from "next-themes";
import { useState, type ReactNode } from "react";

/**
 * Server-state and theme providers.
 *
 * The query client is created inside component state rather than at module
 * scope so each server render gets its own instance and cached data is never
 * shared between users.
 *
 * `ThemeProvider` closes DEV-056. `globals.css` has carried a complete `.dark`
 * palette since Phase 0 and nothing ever added the class — `docs/08-ui-ux.md`
 * says "design for both from the beginning", and half of that had been true for
 * eleven phases. `suppressHydrationWarning` was already on `<html>`, which is
 * what this needs and what suggests it was always meant to be here.
 *
 * `defaultTheme="system"` rather than "light": the correct default is the one
 * the reader already told their operating system, and asking again is a worse
 * answer than listening.
 */
export function Providers({ children }: { children: ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 30_000,
            retry: 1,
          },
        },
      }),
  );

  return (
    <ThemeProvider attribute="class" defaultTheme="system" enableSystem disableTransitionOnChange>
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    </ThemeProvider>
  );
}
