import type { Metadata } from "next";

import { Providers } from "@/app/providers";

import "./globals.css";

export const metadata: Metadata = {
  title: "Job Intelligence Platform",
  description: "Personal AI-powered job search and career intelligence platform.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      {/*
        Fonts come from the system stack rather than next/font/google: a webfont
        fetch at build time makes `next build` fail on a network-restricted
        runner for a purely cosmetic dependency.
      */}
      <body className="font-sans antialiased">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
