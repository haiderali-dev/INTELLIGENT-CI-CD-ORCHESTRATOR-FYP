/** 4.7.4's progress line, in order. The backend sends the steps it reached (generation._progress). */
export const PROGRESS_STEPS = ["Understood", "Planned", "Rendered", "Validated"] as const;
export type ProgressStepName = (typeof PROGRESS_STEPS)[number];

export interface ProgressStep {
  step: ProgressStepName;
  ok: boolean;
  /** For a step that passed, how; for one that failed, the exact error. */
  detail: string;
}

/** One check from the validation checklist (4.6.3), in the backend's order. */
export interface ValidationCheck {
  name: string;
  label: string;
  status: "passed" | "warning" | "failed";
  message: string | null;
}

/** What a screen reader hears when the line changes: "Validated", or the step that failed and
 * why (DESIGN.md section 8). Empty until there is a result to give. */
export function progressAnnouncement(steps: readonly ProgressStep[]): string {
  const failed = steps.find(({ ok }) => !ok);
  if (failed) {
    return `${failed.step} failed: ${failed.detail}`;
  }
  return steps.some(({ step }) => step === "Validated") ? "Validated" : "";
}
