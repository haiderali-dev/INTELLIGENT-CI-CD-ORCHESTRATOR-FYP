import { cn } from "@/lib/cn";

import { BUILD_STATES, type BuildState } from "./buildState";

/**
 * A state as an icon and a word (DESIGN.md principle 2: a state is a word first, and colour is the
 * third cue). `label` replaces the word when the state belongs to something with a name, as in
 * "Build succeeded".
 */
export function BuildStateLabel({
  state,
  label,
  className,
}: {
  state: BuildState;
  label?: string;
  className?: string;
}) {
  const { word, icon: Icon, tone } = BUILD_STATES[state];
  return (
    <span className={cn("inline-flex items-center gap-1.5", className)}>
      <Icon
        aria-hidden="true"
        className={cn(
          "size-4 shrink-0",
          tone,
          // The one thing that loops (DESIGN.md section 7), and it stops under reduced motion.
          state === "running" && "animate-spin motion-reduce:animate-none",
        )}
      />
      <span>{label ?? word}</span>
    </span>
  );
}
