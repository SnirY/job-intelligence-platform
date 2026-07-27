import { JobDetail } from "@/features/jobs/job-detail";

/**
 * Next 15 passes route params as a promise, so the page is async and awaits
 * them before rendering.
 */
export default async function JobDetailPage({ params }: { params: Promise<{ jobId: string }> }) {
  const { jobId } = await params;

  return (
    <div className="mx-auto max-w-4xl">
      <JobDetail jobId={jobId} />
    </div>
  );
}
