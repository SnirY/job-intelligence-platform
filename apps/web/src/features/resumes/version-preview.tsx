"use client";

import { Printer } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Callout } from "@/components/ui/callout";
import { useRenderVersion } from "@/features/resumes/api";

/**
 * The page as it will actually print, beside the editor that makes it.
 *
 * The screen had a button that opened a blank tab and wrote a rendered document
 * into it, and three things were wrong with that at once.
 *
 * **A blocked popup was silent.** `window.open` returns `null` when a browser
 * refuses, and the handler read `if (!tab) return`. The click did nothing,
 * reported nothing, and left somebody pressing a button that had already run.
 *
 * **The tab was blank while the render ran**, then closed itself on failure —
 * so from the tab's side the product opened a window and took it away again.
 *
 * **And nothing showed the page without leaving the screen.** A resume is a
 * document; not being able to see it while writing it is the one thing an
 * editor for a document has to fix.
 *
 * All three answer to the same thing: the render is fetched once, held here,
 * and shown here. The tab becomes somewhere to send a document that already
 * exists rather than the only way to look at one.
 */
export function VersionPreview({ versionId }: { versionId: string }) {
  const render = useRenderVersion();
  const [html, setHtml] = useState<string | null>(null);
  const [blocked, setBlocked] = useState(false);

  const load = (then?: (html: string) => void) => {
    setBlocked(false);
    render.mutate(versionId, {
      onSuccess: (rendered) => {
        setHtml(rendered);
        then?.(rendered);
      },
    });
  };

  const openInTab = (rendered: string) => {
    // No `noopener`: it severs the handle and returns null, and the handle is
    // what we write into. Safe because the tab starts at about:blank and the
    // only thing that reaches it is our own render of the user's own document.
    const tab = window.open("", "_blank");
    if (!tab) {
      setBlocked(true);
      return;
    }
    tab.document.write(rendered);
    tab.document.close();
  };

  return (
    <section aria-labelledby="preview-heading" className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 id="preview-heading" className="text-sm font-medium">
          The page
        </h3>

        <div className="flex flex-wrap items-center gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={render.isPending}
            onClick={() => load()}
          >
            {render.isPending ? "Rendering…" : html ? "Refresh" : "Show the page"}
          </Button>

          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={render.isPending}
            onClick={() => (html ? openInTab(html) : load(openInTab))}
          >
            <Printer aria-hidden className="size-4" />
            Print
          </Button>
        </div>
      </div>

      {render.isError && (
        <Callout tone="caution">
          {/* Said here rather than in a tab that closes itself. The document is
              unchanged either way — a render that fails has not touched it. */}
          The page could not be rendered. Your resume is unchanged; try again in a moment.
        </Callout>
      )}

      {blocked && (
        <Callout tone="caution">
          {/* The case that used to be a button doing nothing. It has an answer
              now only because the render is already on this screen. */}
          Your browser blocked the print window. The page is below, and printing from there works
          the same way.
        </Callout>
      )}

      {html ? (
        <>
          <div className="overflow-auto rounded-md border bg-muted p-4">
            {/*
              A4 at true proportion — 1 / 1.4142 — so the preview is the shape of
              the paper rather than the shape of the pane. A document that looks
              right on screen and wrong on the page is worse than no preview.

              `sandbox` with nothing allowed: the markup is our own server's
              render of the user's own resume, and it has no reason to run a
              script, follow a form, or reach the parent.
            */}
            <iframe
              title="The rendered resume"
              srcDoc={html}
              sandbox=""
              className="mx-auto block aspect-[1/1.4142] w-full max-w-[46rem] bg-white"
            />
          </div>

          <p className="text-xs text-foreground-faint">
            {/* The render is of the saved version, and the editor above may have
                moved since. Stated rather than left for somebody to discover by
                printing an old draft. */}
            This is the last saved version. Changes you have not saved are not on it yet.
          </p>
        </>
      ) : (
        !render.isPending && (
          <p className="text-xs text-muted-foreground">
            Nothing is rendered yet. Showing the page fetches it from the server, so it is exactly
            what would print.
          </p>
        )
      )}
    </section>
  );
}
