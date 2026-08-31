"use client";

import { UserButton } from "@clerk/nextjs";
import { Menu, X } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { usePathname } from "next/navigation";

import { LocalUserButton } from "@/features/auth/local-user-button";
import { CommandPalette } from "@/features/navigation/command-palette";
import { SidebarNav } from "@/features/navigation/sidebar-nav";
import { ThemeToggle } from "@/features/navigation/theme-toggle";
import { Button } from "@/components/ui/button";
import { useModalFocus } from "@/components/ui/use-modal-focus";
import { isLocalAuth } from "@/lib/auth-mode";

/**
 * Authenticated application frame: fixed sidebar on desktop, drawer on mobile.
 *
 * The sidebar is one `SidebarNav` rendered twice rather than two navigations,
 * so the desktop and mobile menus cannot drift apart.
 */
export function AppShell({ children }: { children: ReactNode }) {
  const [drawerOpen, setDrawerOpen] = useState(false);

  /* Close focused on the close button rather than the first nav link: the
     drawer's first act should be to say how to leave it, and a reader who
     opened a menu by mistake is one key from undoing that. */
  const drawer = useModalFocus<HTMLElement>({
    open: drawerOpen,
    onDismiss: () => setDrawerOpen(false),
    initialFocus: "[data-drawer-close]",
  });
  const pathname = usePathname();

  // Navigating with the drawer open would otherwise leave it covering the page
  // the user just asked for.
  useEffect(() => {
    setDrawerOpen(false);
  }, [pathname]);

  /* Escape used to be handled here, on `window`, and it was the one part of the
     contract this drawer already kept. It moved into the hook with the rest:
     focus now enters the panel on open and is trapped there, so a key event
     always reaches it, and the hook's version restores focus on the way out
     while a window listener cannot. */

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
          <div className="absolute inset-0 bg-black/50" onClick={drawer.dismiss} aria-hidden />
          {/*
            F31, finally where it was recorded.

            This drawer is the overlay that entry describes, and it is the one
            that never got the fix: it promised `aria-modal` while Tab walked
            straight out of it, took no focus when it opened, and gave none
            back when it closed. Both other overlays cite F31 in their own
            comments as the reason they do all of that.

            Escape it did already handle, on a window listener — the one part
            of the contract that was here. Worth saying because the first read
            of this file said otherwise.
          */}
          <aside
            ref={drawer.panelRef}
            onKeyDown={drawer.onKeyDown}
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
                data-drawer-close
                onClick={drawer.dismiss}
                aria-label="Close menu"
              >
                <X aria-hidden className="size-4" />
              </Button>
            </div>
            {/* Navigating away closes it, and focus goes with the navigation
                rather than back to the button that opened a menu which is no
                longer on screen. */}
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
            <ThemeToggle />
            {/*
              Sign-out destination comes from the Clerk instance configuration;
              v7 removed the per-component afterSignOutUrl prop. The middleware
              sends a signed-out visitor to /sign-in regardless.
            */}
            {isLocalAuth ? (
              <LocalUserButton />
            ) : (
              <UserButton appearance={{ elements: { avatarBox: "size-8" } }} />
            )}
          </div>
        </header>

        <main id="main-content" className="px-4 py-8 sm:px-6 lg:px-8">
          {children}
        </main>

        {/* Mounted at the shell so the binding exists on every screen. A
            palette that only works on the screen you already reached is not
            worth the key. */}
        <CommandPalette />
      </div>
    </div>
  );
}
