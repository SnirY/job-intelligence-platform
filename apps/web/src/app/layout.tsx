import { ClerkProvider } from "@clerk/nextjs";
import type { Metadata } from "next";

import { fontVariables } from "@/app/fonts";
import { Providers } from "@/app/providers";

import "./globals.css";

export const metadata: Metadata = {
  title: "Job Intelligence Platform",
  description: "Personal AI-powered job search and career intelligence platform.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <ClerkProvider>
      {/*
        Font variables sit on `<html>` rather than on `<body>` so that content
        rendered outside the body's subtree — Clerk's widgets, and any portalled
        dialog — resolves them too. `@/app/fonts` explains why the files are
        vendored.
      */}
      <html lang="en" className={fontVariables} suppressHydrationWarning>
        <body className="font-sans antialiased">
          <Providers>{children}</Providers>
        </body>
      </html>
    </ClerkProvider>
  );
}
