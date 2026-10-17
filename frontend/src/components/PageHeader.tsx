import type { ReactNode } from "react";

import { PRODUCT_NAME, ACCENT_BORDER, type Accent } from "@/app/shell/nav";
import { cn } from "@/lib/cn";

/** A page's name and one sentence on what it is for. An assistant's header carries its accent as a
 * 4px rule, so the two are never confused (DESIGN.md principle 5). `aside` holds the page's own
 * status, such as the queue's "5 waiting", on the right, or under the title on a narrow screen. */
export function PageHeader({
  title,
  description,
  accent,
  aside,
}: {
  title: string;
  description?: string;
  accent?: Accent;
  aside?: ReactNode;
}) {
  return (
    <header
      className={cn(
        "flex flex-wrap items-start justify-between gap-x-6 gap-y-3 border-b border-rule px-6 py-5",
        accent && cn("border-l-4", ACCENT_BORDER[accent]),
      )}
    >
      <title>{`${title} - ${PRODUCT_NAME}`}</title>
      <div>
        <h1 className="text-xl font-semibold">{title}</h1>
        {description ? <p className="mt-1 max-w-[68ch] text-base text-graphite">{description}</p> : null}
      </div>
      {aside}
    </header>
  );
}
