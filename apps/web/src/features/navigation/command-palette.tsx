"use client";

import { DESTINATIONS } from "@/features/navigation/destinations";
import { CornerDownLeft, Search } from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { useJobs } from "@/features/jobs/api";
import { cn } from "@/lib/utils";

/**
 * Search and jump, on one key.
 *
 * The audit of 2026-08-11 asked for this and called it the cheapest item on its
 * list: the most frequent action in the product took two navigations, and there
 * were no keyboard shortcuts at all. What separates a tool from a website here
 * is not how it looks — it is whether someone adding thirty jobs a week has to
 * reach for the mouse to do it.
 *
 * Jobs are searched through the same `useJobs` the list uses, so the palette
 * cannot find something the list would not, and a job that is filtered out of
 * existence for one is missing from both.
 */
const PAGE_SIZE = 6;

type Entry = { id: string; label: string; hint: string; href: string };

export function CommandPalette() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [term, setTerm] = useState("");
  const [cursor, setCursor] = useState(0);

  const inputRef = useRef<HTMLInputElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  // Where focus was before the palette took it. Restoring it is what stops a
  // keyboard user landing back at the top of the document on close — the defect
  // F31 recorded against the mobile drawer.
  const opener = useRef<HTMLElement | null>(null);

  const jobs = useJobs({ search: term.trim() || undefined, page: 1, page_size: PAGE_SIZE });

  const entries = useMemo<Entry[]>(() => {
    const needle = term.trim().toLowerCase();

    const places = DESTINATIONS.filter(
      (destination) => !needle || destination.label.toLowerCase().includes(needle),
    ).map((destination) => ({
      id: `place:${destination.href}`,
      label: destination.label,
      hint: "Go to",
      href: destination.href,
    }));

    // Only once there is something to search by. An empty palette listing six
    // arbitrary jobs would be a list, and there is already a list.
    const matches = needle
      ? (jobs.data?.data ?? []).map((job) => ({
          id: `job:${job.id}`,
          label: job.title,
          hint: job.company ?? "Job",
          href: `/jobs/${job.id}`,
        }))
      : [];

    return [...places, ...matches];
  }, [term, jobs.data]);

  const close = useCallback(() => {
    setOpen(false);
    setTerm("");
    setCursor(0);
    opener.current?.focus();
  }, []);

  const go = useCallback(
    (entry: Entry) => {
      close();
      router.push(entry.href);
    },
    [close, router],
  );

  // The one global binding. `metaKey` and `ctrlKey` together rather than by
  // platform, because a Windows keyboard on a Mac and a Mac keyboard on Linux
  // are both ordinary, and guessing wrong costs the shortcut entirely.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key.toLowerCase() === "k" && (event.metaKey || event.ctrlKey)) {
        event.preventDefault();
        opener.current = document.activeElement as HTMLElement | null;
        setOpen((current) => !current);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  useEffect(() => {
    setCursor(0);
  }, [term]);

  if (!open) return null;

  const onKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === "Escape") {
      event.preventDefault();
      close();
      return;
    }

    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (entries.length === 0) return;
      const step = event.key === "ArrowDown" ? 1 : -1;
      setCursor((current) => (current + step + entries.length) % entries.length);
      return;
    }

    if (event.key === "Enter") {
      event.preventDefault();
      const entry = entries[cursor];
      if (entry) go(entry);
      return;
    }

    // Focus stays inside while it is open. `aria-modal` promises a screen
    // reader that what is behind is unreachable, and Tab running on to the page
    // underneath makes that promise false — worse than never making it.
    if (event.key === "Tab") {
      const focusable = panelRef.current?.querySelectorAll<HTMLElement>(
        'input, button, [href], [tabindex]:not([tabindex="-1"])',
      );
      if (!focusable || focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first?.focus();
      } else if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last?.focus();
      }
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-foreground/20 p-4 pt-[12vh]"
      onClick={close}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label="Search or jump"
        className="w-full max-w-lg overflow-hidden rounded-xl border bg-popover shadow-lg"
        onClick={(event) => event.stopPropagation()}
        onKeyDown={onKeyDown}
      >
        <div className="flex items-center gap-2 border-b px-3">
          <Search aria-hidden className="size-4 shrink-0 text-muted-foreground" />
          <input
            ref={inputRef}
            value={term}
            onChange={(event) => setTerm(event.target.value)}
            placeholder="Search jobs, or jump to a screen"
            aria-label="Search jobs, or jump to a screen"
            className="h-11 w-full bg-transparent text-sm outline-none placeholder:text-muted-foreground"
          />
        </div>

        {entries.length === 0 ? (
          <p className="px-4 py-6 text-sm text-muted-foreground">
            {term.trim() ? `Nothing matches "${term.trim()}".` : "Type to search."}
          </p>
        ) : (
          <ul className="max-h-80 overflow-y-auto py-1">
            {entries.map((entry, index) => (
              <li key={entry.id}>
                <button
                  type="button"
                  // The pointer moves the same cursor the arrows do, so hovering
                  // and then pressing Enter opens what is under the pointer
                  // rather than what the arrows last left behind.
                  onMouseEnter={() => setCursor(index)}
                  onClick={() => go(entry)}
                  aria-current={index === cursor}
                  className={cn(
                    "flex w-full items-center gap-3 px-4 py-2 text-left text-sm",
                    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring",
                    index === cursor && "bg-muted",
                  )}
                >
                  <span className="w-16 shrink-0 text-xs text-muted-foreground">{entry.hint}</span>
                  <span className="truncate">{entry.label}</span>
                  {index === cursor && (
                    <CornerDownLeft
                      aria-hidden
                      className="ml-auto size-3.5 text-muted-foreground"
                    />
                  )}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
