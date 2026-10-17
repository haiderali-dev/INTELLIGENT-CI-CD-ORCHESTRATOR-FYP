import { CircleAlert } from "lucide-react";
import { AlertDialog } from "radix-ui";
import { useId, useState } from "react";

import { failureMessage, type Failure } from "@/api/errors";
import { button } from "@/components/button";
import { useToast } from "@/components/toast/toastContext";

export type ApproveResult = { ok: true } | { ok: false; failure: Failure };

/** The one name for this action through the whole flow (DESIGN.md principle 4). */
export const APPROVE_LABEL = "Approve and run";
export const RUN_STARTED = "Run started";

/**
 * Approve and run (4.7.4). The dialog states exactly what will happen, in the backend's own
 * sentence, such as "Creates 3 jobs and starts fs-payment-service-build on main at HIGH priority".
 * The button says Approve and run; the toast says Run started. Everything works from the keyboard
 * (a 4.7.6 flow). A refusal stays in the dialog with the reason and what to do, rather than
 * closing on a run that never started.
 */
export function ApproveAndRun({
  summary,
  ready,
  approvedAt = null,
  onApprove,
}: {
  /** What approving will do. Null until the plan is validated. */
  summary: string | null;
  /** True once every check has passed. */
  ready: boolean;
  /** When this plan was approved. A plan runs once: approving it again is refused. */
  approvedAt?: string | null;
  onApprove: () => Promise<ApproveResult>;
}) {
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState(false);
  const [failure, setFailure] = useState<Failure | null>(null);
  const toast = useToast();
  const hintId = useId();
  const available = ready && summary !== null;

  const approve = async () => {
    if (pending) {
      return;
    }
    setPending(true);
    setFailure(null);
    const result = await onApprove();
    setPending(false);
    if (result.ok) {
      setOpen(false);
      toast(RUN_STARTED);
    } else {
      setFailure(result.failure);
    }
  };

  if (approvedAt !== null && !open) {
    return (
      <p className="text-sm">
        <span className="font-semibold">Approved and started. </span>
        <span className="text-graphite">The run card in the conversation follows the run.</span>
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      <AlertDialog.Root
        open={open}
        onOpenChange={(next) => {
          if (!pending) {
            setOpen(next);
            setFailure(null);
          }
        }}
      >
        <AlertDialog.Trigger asChild>
          <button
            type="button"
            aria-disabled={!available}
            aria-describedby={available ? undefined : hintId}
            onClick={(event) => {
              if (!available) {
                event.preventDefault();
              }
            }}
            className={button({ variant: "primary" })}
          >
            {APPROVE_LABEL}
          </button>
        </AlertDialog.Trigger>
        <AlertDialog.Portal>
          <AlertDialog.Overlay className="fixed inset-0 z-40 bg-ink/40" />
          <AlertDialog.Content className="fixed top-1/2 left-1/2 z-50 flex w-[32rem] max-w-[calc(100vw-2rem)] -translate-x-1/2 -translate-y-1/2 flex-col gap-4 rounded-float bg-panel p-6 text-ink shadow-float dark:border dark:border-rule">
            <AlertDialog.Title className="text-lg font-semibold">{APPROVE_LABEL}</AlertDialog.Title>
            <AlertDialog.Description className="max-w-[68ch]">{summary}</AlertDialog.Description>
            {failure ? (
              <p role="alert" className="flex gap-2 border-l-4 border-ink bg-ground px-3 py-2 text-sm">
                <CircleAlert aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
                <span>{failureMessage(failure)}</span>
              </p>
            ) : null}
            <div className="flex flex-wrap justify-end gap-2">
              <AlertDialog.Cancel asChild>
                <button type="button" aria-disabled={pending} className={button()}>
                  Cancel
                </button>
              </AlertDialog.Cancel>
              <AlertDialog.Action asChild>
                <button
                  type="button"
                  aria-disabled={pending}
                  onClick={(event) => {
                    // The dialog closes itself on Action; it stays open until the run starts.
                    event.preventDefault();
                    void approve();
                  }}
                  className={button({ variant: "primary" })}
                >
                  {pending ? "Starting" : APPROVE_LABEL}
                </button>
              </AlertDialog.Action>
            </div>
          </AlertDialog.Content>
        </AlertDialog.Portal>
      </AlertDialog.Root>
      {available ? null : (
        <p id={hintId} className="text-sm text-graphite">
          Available once every check passes.
        </p>
      )}
    </div>
  );
}
