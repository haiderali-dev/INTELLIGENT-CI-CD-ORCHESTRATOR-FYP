import { CircleAlert, CircleCheck, CircleDashed, CircleX } from "lucide-react";

import {
  PROGRESS_STEPS,
  progressAnnouncement,
  type ProgressStep,
  type ValidationCheck,
} from "./progress";

/**
 * Understood, Planned, Rendered, Validated (4.7.4), each with a check or the exact error. These
 * are not build states, so the icons are Ink and the words carry the meaning; the state colours
 * stay with builds (DESIGN.md section 2). A step after a failure was never reached, and says so.
 */
export function ProgressSteps({ steps }: { steps: readonly ProgressStep[] }) {
  return (
    <div className="flex flex-col gap-2">
      <ol aria-label="Progress" className="flex flex-col gap-2">
        {PROGRESS_STEPS.map((name) => {
          const step = steps.find((candidate) => candidate.step === name);
          if (!step) {
            return (
              <li key={name} className="flex items-start gap-2 text-graphite">
                <CircleDashed aria-hidden="true" className="mt-1 size-4 shrink-0" />
                <span>
                  {name}
                  <span className="sr-only">, not reached</span>
                </span>
              </li>
            );
          }
          return step.ok ? (
            <li key={name} className="flex items-start gap-2">
              <CircleCheck aria-hidden="true" className="mt-1 size-4 shrink-0 text-ink" />
              <span className="flex flex-col">
                <span>{name}</span>
                <span className="text-sm text-graphite">{step.detail}</span>
              </span>
            </li>
          ) : (
            <li key={name} className="flex items-start gap-2">
              <CircleX aria-hidden="true" className="mt-1 size-4 shrink-0 text-ink" />
              <span className="flex flex-col">
                <span className="font-semibold">{`${name} failed`}</span>
                <span>{step.detail}</span>
              </span>
            </li>
          );
        })}
      </ol>
      <p aria-live="polite" className="sr-only">
        {progressAnnouncement(steps)}
      </p>
    </div>
  );
}

const CHECK_LOOK = {
  passed: { word: "Passed", icon: CircleCheck },
  warning: { word: "Warning", icon: CircleAlert },
  failed: { word: "Failed", icon: CircleX },
} as const;

/** The validation checklist (4.6.3), each check with its result as an icon and a word. */
export function ValidationChecklist({ checks }: { checks: readonly ValidationCheck[] }) {
  if (checks.length === 0) {
    return <p className="text-sm text-graphite">No checks have run yet.</p>;
  }
  return (
    <ul aria-label="Checks" className="flex flex-col gap-2">
      {checks.map(({ name, label, status, message }) => {
        const { word, icon: Icon } = CHECK_LOOK[status];
        return (
          <li key={name} className="flex items-start gap-2">
            <Icon
              aria-hidden="true"
              className={status === "passed" ? "mt-1 size-4 shrink-0 text-graphite" : "mt-1 size-4 shrink-0 text-ink"}
            />
            <span className="flex flex-col">
              <span>
                {label}
                <span className="text-graphite">{`: ${word}`}</span>
              </span>
              {message && status !== "passed" ? <span className="text-sm">{message}</span> : null}
            </span>
          </li>
        );
      })}
    </ul>
  );
}
