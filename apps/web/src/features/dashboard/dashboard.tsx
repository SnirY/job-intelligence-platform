"use client";

import {
  actionHref,
  APPLICATION_STATUS_LABELS,
  NEXT_ACTION_LABELS,
  type ActivityEntry,
  type Dashboard,
  type DashboardOpportunity,
  type NextAction,
  type PipelineStage,
  type SkillGap,
} from "@jip/shared-types";
import { ArrowRight, CircleAlert, Sparkles, Target } from "lucide-react";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useDashboard } from "@/features/dashboard/api";

/**
 * The home screen.
 *
 * `docs/08-ui-ux.md` asks every important screen to answer three questions, and
 * the section order is that answer rather than a layout preference:
 *
 * 1. *What am I looking at?* — the counts at the top.
 * 2. *What should I do next?* — the actions, immediately after, because a
 *    dashboard whose first offer is a chart is a report.
 * 3. *Why does it matter?* — every action and opportunity carries the fact it
 *    came from, so none of it has to be taken on trust.
 *
 * Nothing here is computed. Every number is a count of rows the user can go and
 * look at, and every claim links to the screen it was read from. The same rule
 * that keeps a match honest keeps a dashboard from becoming a horoscope.
 */
export function DashboardScreen({ greeting }: { greeting: string }) {
  const query = useDashboard();

  if (query.isPending) {
    return <Shell greeting={greeting}>Loading where things stand…</Shell>;
  }

  if (query.isError || !query.data) {
    return (
      <Shell greeting={greeting} tone="error">
        Could not load your dashboard. Your data is unaffected — try reloading.
      </Shell>
    );
  }

  const data = query.data;
  const started = data.state.jobs_saved > 0 || data.state.profile_skills > 0;

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <header className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight">{greeting}</h1>
        <p className="text-muted-foreground">
          {started
            ? "Where everything stands, and what is worth doing next."
            : "Nothing here yet. The two steps below are where this starts."}
        </p>
      </header>

      {started && <CurrentState data={data} />}

      <NextActions actions={data.actions} />

      {data.opportunities.length > 0 && <Opportunities items={data.opportunities} />}
      {data.pipeline.length > 0 && <Pipeline stages={data.pipeline} />}

      <div className="grid gap-6 md:grid-cols-2">
        {data.skill_gaps.length > 0 && <SkillGaps gaps={data.skill_gaps} />}
        {data.activity.length > 0 && <Activity entries={data.activity} />}
      </div>
    </div>
  );
}

/** The counts. Each one is a number of rows, and each links to them. */
function CurrentState({ data }: { data: Dashboard }) {
  const { state } = data;

  const figures: { label: string; value: number; href: string }[] = [
    { label: "Jobs saved", value: state.jobs_saved, href: "/jobs" },
    { label: "Read into requirements", value: state.jobs_analysed, href: "/jobs" },
    { label: "Compared to your profile", value: state.jobs_matched, href: "/jobs" },
    { label: "Applications live", value: state.applications_live, href: "/applications" },
    { label: "Skills on your profile", value: state.profile_skills, href: "/career-profile" },
  ];

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
      {figures.map((figure) => (
        <Link
          key={figure.label}
          href={figure.href}
          className="rounded-lg border p-4 transition-colors hover:bg-muted"
        >
          <p className="text-2xl font-semibold tabular-nums">{figure.value}</p>
          <p className="mt-1 text-xs text-muted-foreground">{figure.label}</p>
        </Link>
      ))}
    </div>
  );
}

/**
 * The most useful section, and the reason the screen exists.
 *
 * Capped at five by the backend. `docs/07` asks for "a small prioritized set,
 * not dozens of recommendations" — a list long enough to need scanning is one
 * that gets ignored, and the items past the fold are by construction the least
 * urgent.
 */
function NextActions({ actions }: { actions: NextAction[] }) {
  if (actions.length === 0) {
    return (
      <Card>
        <CardContent className="flex items-center gap-3 p-6">
          <Sparkles aria-hidden className="size-4 shrink-0 text-muted-foreground" />
          <p className="text-sm">
            Nothing is waiting on you. Every job you have saved has been read, compared, and is
            either applied to or set aside.
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">What to do next</CardTitle>
        <CardDescription>
          Each one says what it is based on, so you can disagree with it.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        {actions.map((action) => (
          <Link
            key={`${action.kind}-${action.job_id ?? action.subject}`}
            href={actionHref(action)}
            className="flex items-start justify-between gap-3 rounded-md border p-3 transition-colors hover:bg-muted"
          >
            <div className="min-w-0 space-y-1">
              <p className="text-sm font-medium">
                {NEXT_ACTION_LABELS[action.kind]}
                {action.kind !== "BUILD_PROFILE" && (
                  <span className="text-muted-foreground"> — {action.subject}</span>
                )}
              </p>
              <p className="text-xs text-muted-foreground">{action.reason}</p>
            </div>
            <ArrowRight aria-hidden className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
          </Link>
        ))}
      </CardContent>
    </Card>
  );
}

function Opportunities({ items }: { items: DashboardOpportunity[] }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Target aria-hidden className="size-4 text-muted-foreground" />
          Where you line up best
        </CardTitle>
        <CardDescription>
          Ranked by how much of each posting your profile covers. Not a prediction about interviews
          or offers.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        {items.map((item) => (
          <Link
            key={item.job_id}
            href={`/jobs/${item.job_id}`}
            className="flex items-center justify-between gap-3 rounded-md border p-3 transition-colors hover:bg-muted"
          >
            <div className="min-w-0">
              <p className="truncate text-sm font-medium">{item.title}</p>
              <p className="truncate text-xs text-muted-foreground">
                {item.company ?? "No company recorded"}
                {item.has_application && " · applied"}
              </p>
            </div>
            <div className="flex shrink-0 items-center gap-2">
              {item.is_stale && (
                <Badge variant="outline" className="gap-1">
                  <CircleAlert aria-hidden className="size-3" />
                  Out of date
                </Badge>
              )}
              <div className="text-right">
                <p className="text-sm font-semibold tabular-nums">
                  {item.score === null ? "—" : `${item.score}%`}
                </p>
                <p className="text-xs text-muted-foreground">{item.alignment_label}</p>
              </div>
            </div>
          </Link>
        ))}
      </CardContent>
    </Card>
  );
}

/**
 * Applications by stage.
 *
 * Stages with nothing in them are absent, not zeroed: fourteen columns of which
 * two have anything in them reads as a system with twelve problems.
 */
function Pipeline({ stages }: { stages: PipelineStage[] }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Your pipeline</CardTitle>
        <CardDescription>
          Everything above the line is preparation. Below it, something has been sent.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-wrap gap-2">
        {stages.map((stage) => (
          <Link
            key={stage.status}
            href="/applications"
            className="rounded-md border px-3 py-2 transition-colors hover:bg-muted"
          >
            <span className="text-sm font-semibold tabular-nums">{stage.count}</span>
            <span className="ml-2 text-xs text-muted-foreground">
              {APPLICATION_STATUS_LABELS[stage.status]}
            </span>
            {stage.before_applying && (
              <span className="ml-2 text-[10px] uppercase text-muted-foreground">preparing</span>
            )}
          </Link>
        ))}
      </CardContent>
    </Card>
  );
}

function SkillGaps({ gaps }: { gaps: SkillGap[] }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Asked for, and not on your profile</CardTitle>
        <CardDescription>
          Counted across the jobs you saved — not the market, and not advice about what to learn.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        {gaps.map((gap) => (
          <div key={gap.skill_id} className="flex items-center justify-between gap-3 text-sm">
            <span className="truncate">{gap.name}</span>
            <span className="shrink-0 text-xs text-muted-foreground">
              {gap.asked_by_jobs === 1 ? "1 job" : `${gap.asked_by_jobs} jobs`}
            </span>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

function Activity({ entries }: { entries: ActivityEntry[] }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Recently</CardTitle>
        <CardDescription>What has happened, newest first.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        {entries.map((entry, index) => (
          <div
            key={`${entry.at}-${index}`}
            className="flex items-center justify-between gap-3 text-sm"
          >
            <span className="truncate">{entry.subject}</span>
            <span className="shrink-0 text-xs text-muted-foreground">
              {new Date(entry.at).toLocaleDateString()}
            </span>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

function Shell({
  greeting,
  children,
  tone,
}: {
  greeting: string;
  children: React.ReactNode;
  tone?: "error";
}) {
  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <h1 className="text-2xl font-semibold tracking-tight">{greeting}</h1>
      <Card>
        <CardContent className="p-6">
          <p
            className={
              tone === "error" ? "text-sm text-destructive" : "text-sm text-muted-foreground"
            }
          >
            {children}
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
