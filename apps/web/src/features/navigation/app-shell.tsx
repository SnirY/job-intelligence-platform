"use client";

import { UserButton } from "@clerk/nextjs";
import { Menu, X } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { usePathname } from "next/navigation";

import { SidebarNav } from "@/features/navigation/sidebar-nav";
import { Button } from "@/components/ui/button";

/**
 * Authenticated application frame: fixed sidebar on desktop, drawer on mobile.
 *
 * The sidebar is one `SidebarNav` rendered twice rather than two navigations,
 * so the desktop and mobile menus cannot drift apart.
 */
export function AppShell({ children }: { children: ReactNode }) {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const pathname = usePathname();

  // Navigating with the drawer open would otherwise leave it covering the page
  // the user just asked for.
  useEffect(() => {
    setDrawerOpen(false);
  }, [pathname]);

  // Escape closes the drawer; a menu that can only be dismissed by pointer is
  // a keyboard trap.
  useEffect(() => {
    if (!drawerOpen) return;

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setDrawerOpen(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [drawerOpen]);

  return (
    <div className="min-h-screen bg-background">
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-md focus:bg-primary focus:px-4 focus:py-2 focus:text-primary-foreground"
      >
        Skip to content
      </a>

      {/* Desktop sidebar */}
      <aside className="fixed inset-y-0 left-0 hidden w-60 border-r bg-card lg:block">
        <div className="flex h-14 items-center px-5">
          <span className="text-sm font-semibold tracking-tight">Job Intelligence</span>
        </div>
        <SidebarNav />
      </aside>

      {/* Mobile drawer */}
      {drawerOpen && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div
            className="absolute inset-0 bg-black/50"
            onClick={() => setDrawerOpen(false)}
            aria-hidden
          />
          <aside
            role="dialog"
            aria-modal="true"
            aria-label="Main menu"
            className="absolute inset-y-0 left-0 w-64 border-r bg-card shadow-xl"
          >
            <div className="flex h-14 items-center justify-between px-5">
              <span className="text-sm font-semibold tracking-tight">Job Intelligence</span>
              <Button
                variant="ghost"
                size="icon"
                onClick={() => setDrawerOpen(false)}
                aria-label="Close menu"
              >
                <X aria-hidden className="size-4" />
              </Button>
            </div>
            <SidebarNav onNavigate={() => setDrawerOpen(false)} />
          </aside>
        </div>
      )}

      <div className="lg:pl-60">
        <header className="sticky top-0 z-30 flex h-14 items-center justify-between gap-4 border-b bg-background/80 px-4 backdrop-blur sm:px-6">
          <Button
            variant="ghost"
            size="icon"
            className="lg:hidden"
            onClick={() => setDrawerOpen(true)}
            aria-label="Open menu"
            aria-expanded={drawerOpen}
          >
            <Menu aria-hidden className="size-5" />
          </Button>

          <div className="ml-auto flex items-center gap-3">
            {/*
              Sign-out destination comes from the Clerk instance configuration;
              v7 removed the per-component afterSignOutUrl prop. The middleware
              sends a signed-out visitor to /sign-in regardless.
            */}
            <UserButton appearance={{ elements: { avatarBox: "size-8" } }} />
          </div>
        </header>

        <main id="main-content" className="px-4 py-8 sm:px-6 lg:px-8">
          {children}
        </main>
      </div>
    </div>
  );
}
