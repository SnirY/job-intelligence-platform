"use client";

import { providerLabel, type DiscoveredPosting, type WatchedBoard } from "@jip/shared-types";
import { ExternalLink, Loader2, Pause, Play, RefreshCw, Trash2, X } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Reading } from "@/components/ui/reading";
import { StateCard } from "@/components/ui/state-card";
import {
  useAddBoard,
  useBoardAction,
  useDismissPosting,
  usePendingPostings,
  usePromotePosting,
  useProviders,
  useScan,
  useWatchedBoards,
} from "@/features/discovery/api";
import { ApiError } from "@/lib/api";

/**
 * Discovery: boards to watch, and what they returned.
 *
 * The screen is arranged around the one rule the feature exists to keep. What a
 * scan finds is a **candidate**, not a job, and the two never share a list. A
 * posting only reaches the job library because a person pressed Add — there is
 * no automatic path and the screen should make that obvious rather than merely
 * true.
 *
 * Nothing here shows a score, a match or a requirement, and that is not an
 * omission. Those are readings produced by the analysis pipeline, which a
 * posting reaches after promotion. Showing an alignment figure beside a
 * candidate would mean the system had judged something nobody had chosen.
 */
export function Discovery() {
  const [scanning, setScanning] = useState(false);
  const boards = useWatchedBoards();
  const postings = usePendingPostings({ poll: scanning });
  const scan = useScan();

  const rows = postings.data?.data ?? [];

  function start() {
    scan.mutate(undefined, {
      onSuccess: (result) => {
        // Zero boards is a real answer. Polling for a scan that will not run
        // would spin forever against nothing.
        if (result.boards > 0) {
          setScanning(true);
          setTimeout(() => setScanning(false), 60_000);
        }
      },
    });
  }

  return (
    <Reading>
      <div className="space-y-6">
        <header className="space-y-2">
          <h1 className="text-2xl font-semibold tracking-tight">Discover</h1>
          <p className="text-muted-foreground">
            Watch a company&rsquo;s job board and see what it opens. Nothing here is saved to your
            jobs until you add it.
          </p>
        </header>

        <BoardsPanel boards={boards.data ?? []} loading={boards.isPending} />

        <Card>
          <CardHeader className="flex flex-row items-start justify-between gap-3">
            <div>
              <CardTitle className="text-base">Found on your boards</CardTitle>
              <CardDescription>
                Postings you have not decided about. Adding one saves it as a job; dismissing it
                means a later scan will not offer it again.
              </CardDescription>
            </div>
            <Button
              type="button"
              variant="secondary"
              size="sm"
              disabled={scan.isPending || scanning}
              onClick={start}
            >
              {scanning ? (
                <Loader2 aria-hidden className="size-4 animate-spin" />
              ) : (
                <RefreshCw aria-hidden className="size-4" />
              )}
              {scanning ? "Scanning…" : "Scan now"}
            </Button>
          </CardHeader>
          <CardContent className="space-y-3">
            {scan.isSuccess && scan.data.boards === 0 && (
              <p className="text-sm text-muted-foreground">
                There is nothing to scan yet. Add a board above.
              </p>
            )}

            {postings.isPending && <StateCard>Loading what your boards returned…</StateCard>}
            {postings.isError && <StateCard tone="error">Could not load these postings.</StateCard>}

            {!postings.isPending && !postings.isError && rows.length === 0 && (
              <p className="text-sm text-muted-foreground">
                {scanning
                  ? "Reading your boards…"
                  : "Nothing waiting. Scan your boards to see what has opened."}
              </p>
            )}

            {rows.map((posting) => (
              <PostingRow key={posting.id} posting={posting} />
            ))}
          </CardContent>
        </Card>
      </div>
    </Reading>
  );
}

function PostingRow({ posting }: { posting: DiscoveredPosting }) {
  const router = useRouter();
  const promote = usePromotePosting();
  const dismiss = useDismissPosting();
  const [duplicate, setDuplicate] = useState(false);

  const busy = promote.isPending || dismiss.isPending;

  function add(allowDuplicate = false) {
    promote.mutate(
      { id: posting.id, allow_duplicate: allowDuplicate },
      {
        onSuccess: (result) => router.push(`/jobs/${result.job_id}`),
        onError: (error) => {
          // A board listing something already saved is a normal outcome here,
          // not an edge case, so it gets an answer rather than a red message.
          if (error instanceof ApiError && error.status === 409) setDuplicate(true);
        },
      },
    );
  }

  return (
    <div className="rounded-lg border p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 space-y-1">
          <p className="font-medium">{posting.title}</p>
          <p className="text-sm text-muted-foreground">
            {[posting.company, posting.location].filter(Boolean).join(" · ") || "—"}
          </p>
          <p className="text-xs text-muted-foreground">
            {providerLabel(posting.provider)} · found <bdi>{formatDate(posting.first_seen_at)}</bdi>
            {!posting.has_description && " · no description on the board"}
          </p>
        </div>

        <div className="flex shrink-0 flex-wrap items-center gap-2">
          <a
            href={posting.url}
            target="_blank"
            // noreferrer as well as noopener: the target is a third party's page
            // and there is no reason to hand it ours.
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 text-sm underline underline-offset-4"
          >
            Open
            <ExternalLink aria-hidden className="size-3.5" />
          </a>
          <Button type="button" size="sm" disabled={busy} onClick={() => add()}>
            Add to jobs
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            disabled={busy}
            onClick={() => dismiss.mutate(posting.id)}
          >
            <X aria-hidden className="size-4" />
            Dismiss
          </Button>
        </div>
      </div>

      {duplicate && (
        <div className="mt-3 rounded-md border border-dashed p-3 text-sm">
          <p>You have already saved this job. Add it again?</p>
          <div className="mt-2 flex gap-2">
            <Button type="button" size="sm" variant="secondary" onClick={() => add(true)}>
              Add anyway
            </Button>
            <Button type="button" size="sm" variant="ghost" onClick={() => setDuplicate(false)}>
              Leave it
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

function BoardsPanel({ boards, loading }: { boards: WatchedBoard[]; loading: boolean }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Boards you watch</CardTitle>
        <CardDescription>
          These are company job boards, one company at a time — not a search across the market.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {loading && <StateCard>Loading your boards…</StateCard>}

        {!loading && boards.length === 0 && (
          <p className="text-sm text-muted-foreground">
            No boards yet. Add one below to start seeing what a company opens.
          </p>
        )}

        {boards.map((board) => (
          <BoardRow key={board.id} board={board} />
        ))}

        <AddBoardForm />
      </CardContent>
    </Card>
  );
}

function BoardRow({ board }: { board: WatchedBoard }) {
  const paused = board.paused_at !== null;
  const toggle = useBoardAction(board.id, paused ? "resume" : "pause");
  const remove = useBoardAction(board.id, "remove");

  return (
    <div className="flex flex-wrap items-center justify-between gap-3 border-b pb-3 last:border-0">
      <div className="min-w-0">
        <p className="text-sm font-medium">
          {board.label ?? board.token}
          <span className="ml-2 text-xs font-normal text-muted-foreground">
            {providerLabel(board.provider)}
          </span>
          {paused && <span className="ml-2 text-xs font-normal">· Paused</span>}
        </p>
        {/* Per board, so a company that has stopped being readable is named
          rather than folded into a count. */}
        {board.last_error ? (
          <p className="text-xs text-destructive">{board.last_error}</p>
        ) : (
          <p className="text-xs text-muted-foreground">
            {board.last_scanned_at ? (
              <>
                Last read <bdi>{formatDate(board.last_scanned_at)}</bdi>
              </>
            ) : (
              "Not read yet"
            )}
          </p>
        )}
      </div>

      <div className="flex shrink-0 items-center gap-1">
        <Button
          type="button"
          variant="ghost"
          size="sm"
          disabled={toggle.isPending}
          onClick={() => toggle.mutate()}
        >
          {paused ? (
            <Play aria-hidden className="size-3.5" />
          ) : (
            <Pause aria-hidden className="size-3.5" />
          )}
          {paused ? "Resume" : "Pause"}
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          disabled={remove.isPending}
          onClick={() => remove.mutate()}
        >
          <Trash2 aria-hidden className="size-3.5" />
          Remove
        </Button>
      </div>
    </div>
  );
}

function AddBoardForm() {
  const providers = useProviders();
  const add = useAddBoard();
  const [provider, setProvider] = useState("");
  const [token, setToken] = useState("");
  const [label, setLabel] = useState("");

  const options = providers.data ?? [];
  const chosen = provider || options[0] || "";

  function submit(event: React.FormEvent) {
    event.preventDefault();
    add.mutate(
      { provider: chosen, token: token.trim(), label: label.trim() || null },
      {
        onSuccess: () => {
          setToken("");
          setLabel("");
        },
      },
    );
  }

  return (
    // `minmax(0, 1fr)`, not `1fr`. A bare `1fr` floors at the column's
    // min-content width, and a text input's min-content is its default size —
    // so the two inputs refused to shrink and squeezed the button column until
    // "Watch" wrapped to one letter per line. Found on a real screen.
    <form
      onSubmit={submit}
      className="grid gap-3 border-t pt-4 sm:grid-cols-[auto_minmax(0,1fr)_minmax(0,1fr)_auto]"
    >
      <div className="space-y-1">
        <Label htmlFor="board-provider">Source</Label>
        <select
          id="board-provider"
          className="h-9 rounded-md border bg-background px-2 text-sm"
          value={chosen}
          onChange={(event) => setProvider(event.target.value)}
        >
          {options.map((name) => (
            <option key={name} value={name}>
              {providerLabel(name)}
            </option>
          ))}
        </select>
      </div>

      <div className="min-w-0 space-y-1">
        <Label htmlFor="board-token">Board name</Label>
        <input
          id="board-token"
          className="h-9 w-full rounded-md border bg-background px-2 text-sm"
          value={token}
          onChange={(event) => setToken(event.target.value)}
          placeholder="the company's id on that source"
          required
        />
      </div>

      <div className="min-w-0 space-y-1">
        <Label htmlFor="board-label">Company (optional)</Label>
        <input
          id="board-label"
          className="h-9 w-full rounded-md border bg-background px-2 text-sm"
          value={label}
          onChange={(event) => setLabel(event.target.value)}
          placeholder="what to call it"
        />
      </div>

      <div className="flex items-end">
        <Button type="submit" disabled={add.isPending || !token.trim()}>
          Watch
        </Button>
      </div>

      {add.isError && (
        <p className="text-sm text-destructive sm:col-span-4">
          {add.error instanceof ApiError && add.error.status === 409
            ? "You are already watching that board."
            : "That board could not be added. Check the name and try again."}
        </p>
      )}
    </form>
  );
}

/**
 * A date, in the reader's own locale, and always rendered inside `<bdi>`.
 *
 * The copy around it is English and the format is not. On a right-to-left
 * locale this returns a right-to-left run, and dropping one into a
 * left-to-right sentence without isolation reorders it on screen.
 */
function formatDate(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime())
    ? "an unknown date"
    : parsed.toLocaleDateString(undefined, { day: "numeric", month: "short" });
}
