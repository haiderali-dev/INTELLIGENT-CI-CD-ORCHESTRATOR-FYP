import type { LucideIcon } from "lucide-react";
import { useId, type ReactNode } from "react";

import { failureMessage } from "@/api/errors";
import { failureOf } from "@/api/request";
import { cn } from "@/lib/cn";

import { button } from "./button";

/** A titled part of a page, under the page header. */
export function PageSection({
  title,
  aside,
  children,
  className,
}: {
  title: string;
  /** Beside the title: a count, or an action on the whole section. */
  aside?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  const headingId = useId();
  return (
    <section aria-labelledby={headingId} className={cn("flex flex-col gap-3 py-5", className)}>
      <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-2 px-6">
        <h2 id={headingId} className="text-lg font-semibold">
          {title}
        </h2>
        {aside}
      </div>
      {children}
    </section>
  );
}

/** While the first answer is on its way. */
export function Loading({ children }: { children: ReactNode }) {
  return <p className="px-6 text-graphite">{children}</p>;
}

/** What could not be loaded, why, and the way to try again (4.7.5: errors say how to fix them). */
export function LoadFailed({
  what,
  error,
  onRetry,
}: {
  /** Starts the sentence, as in "The runs". */
  what: string;
  error: unknown;
  onRetry: () => void;
}) {
  return (
    <div role="alert" className="flex flex-col gap-3 px-6">
      <p className="max-w-[68ch]">
        <span className="font-semibold">{`${what} could not be loaded. `}</span>
        {failureMessage(failureOf(error))}
      </p>
      <button type="button" onClick={onRetry} className={cn(button(), "self-start")}>
        Try again
      </button>
    </div>
  );
}

/** Nothing to show yet, and what would fill it (4.7.5: empty states invite an action). */
export function Empty({ children }: { children: ReactNode }) {
  return <div className="flex max-w-[68ch] flex-col gap-3 px-6">{children}</div>;
}

/**
 * A health or reachability word with its icon, in Ink or Graphite. Never a state colour: those
 * belong to build states alone (DESIGN.md section 2).
 */
export function StatusWord({
  icon: Icon,
  word,
  quiet = false,
}: {
  icon: LucideIcon;
  word: string;
  /** Graphite, for a state that is not the normal one. */
  quiet?: boolean;
}) {
  return (
    <span className={cn("inline-flex items-center gap-1.5 font-semibold", quiet && "text-graphite")}>
      <Icon aria-hidden="true" className="size-4 shrink-0" />
      {word}
    </span>
  );
}
