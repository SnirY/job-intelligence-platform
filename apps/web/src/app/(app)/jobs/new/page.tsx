import { AddJobForm } from "@/features/jobs/add-job-form";

export default function AddJobPage() {
  return (
    <div className="mx-auto max-w-3xl space-y-8">
      <header className="space-y-2">
        <h1 className="text-2xl font-semibold tracking-tight">Add a job</h1>
        <p className="text-muted-foreground">
          Keep a role somewhere you can come back to. We store the posting as it arrived, so it is
          still readable after the listing comes down.
        </p>
      </header>

      <AddJobForm />
    </div>
  );
}
