import type { components } from "@/api/schema";

/** One step of 4.7.4's progress line, as the API sends it (D-058). */
export type ProgressStep = components["schemas"]["ProgressStep"];
export type ProgressStepName = ProgressStep["step"];

/** One check from the validation checklist (4.6.3), as the API sends it (D-058). */
export type ValidationCheck = components["schemas"]["ValidationCheck"];

/** The line's order. The API sends only the steps it reached; the rest show as not reached. */
export const PROGRESS_STEPS = [
  "Understood",
  "Planned",
  "Rendered",
  "Validated",
] as const satisfies readonly ProgressStepName[];

/** What a screen reader hears when the line changes: "Validated", or the step that failed and
 * why (DESIGN.md section 8). Empty until there is a result to give. */
export function progressAnnouncement(steps: readonly ProgressStep[]): string {
  const failed = steps.find(({ ok }) => !ok);
  if (failed) {
    return `${failed.step} failed: ${failed.detail}`;
  }
  return steps.some(({ step }) => step === "Validated") ? "Validated" : "";
}
