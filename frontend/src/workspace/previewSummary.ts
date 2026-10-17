import type { Pipeline } from "@/api/assistantApi";

/** The bottom sheet's handle under 768 px (DESIGN.md section 4): what the preview holds, in one
 * line, such as "Preview: 3 jobs, all checks pass". */
export function previewSummary(pipeline: Pipeline | null | undefined): string {
  if (!pipeline) {
    return "Preview: nothing generated yet";
  }
  if (pipeline.status === "APPROVED") {
    return "Preview: approved and started";
  }
  const jobs = pipeline.jobs.length;
  const counted = `${jobs} ${jobs === 1 ? "job" : "jobs"}`;
  const failed = pipeline.validation?.checks.filter(({ status }) => status === "failed").length ?? 0;
  if (pipeline.status === "VALIDATED") {
    return `Preview: ${counted}, all checks pass`;
  }
  if (failed > 0) {
    return `Preview: ${failed} ${failed === 1 ? "check" : "checks"} failed`;
  }
  return "Preview: the plan did not pass validation";
}
