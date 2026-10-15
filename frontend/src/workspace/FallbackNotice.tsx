import { Info } from "lucide-react";

/**
 * When the rule parser answered instead of the model (4.7.4): one line inside the message, never a
 * modal. Health is not a build state, so it is Graphite with an icon, not amber or red.
 */
export function FallbackNotice() {
  return (
    <p className="flex items-start gap-1.5 text-sm text-graphite">
      <Info aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
      <span>
        The rule parser answered this, because the AI model was not available. It understands the
        commands in /help.
      </span>
    </p>
  );
}
