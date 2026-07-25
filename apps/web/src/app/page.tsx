import { ApiStatusCard } from "@/features/system/api-status-card";

export default function Home() {
  return (
    <main className="mx-auto flex min-h-screen max-w-4xl flex-col justify-center gap-8 px-6 py-16">
      <header className="space-y-2">
        <h1 className="text-3xl font-semibold tracking-tight">Job Intelligence Platform</h1>
        <p className="text-muted-foreground">
          Phase 0 — project foundation. No product features are implemented yet; this page exists to
          confirm the frontend can reach the backend.
        </p>
      </header>

      <ApiStatusCard />
    </main>
  );
}
