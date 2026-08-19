import { JobDetail } from "@/features/jobs/job-detail";

/**
 * Next 15 passes route params as a promise, so the page is async and awaits
 * them before rendering.
 */
export default async function JobDetailPage({ params }: { params: Promise<{ jobId: string }> }) {
  const { jobId } = await params;

  return (
    /* Wider than the rest of the app, because one panel on this page is a
       three-pane workspace and the others are prose. `JobDetail` keeps the
       prose at a reading measure itself; the page only has to stop being the
       thing that caps it. */
    <div className="mx-auto max-w-[1600px]">
      <JobDetail jobId={jobId} />
    </div>
  );
}
