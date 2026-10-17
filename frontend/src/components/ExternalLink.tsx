import { ExternalLink as ExternalLinkIcon } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "@/lib/cn";

/** A link out must be a web address, never a script. */
function isWebAddress(url: string): boolean {
  return /^https?:\/\//i.test(url);
}

/**
 * A link that leaves the app, saying so: the external-link icon, and "opens in a new tab" for
 * screen readers (DESIGN.md section 9). Anything but a web address is shown as text.
 */
export function ExternalLink({
  href,
  children,
  className,
}: {
  href: string;
  children: ReactNode;
  className?: string;
}) {
  if (!isWebAddress(href)) {
    return <span className={className}>{children}</span>;
  }
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className={cn("inline-flex items-center gap-1 underline underline-offset-4", className)}
    >
      {children}
      <ExternalLinkIcon aria-hidden="true" className="size-4 shrink-0" />
      {/* Inline names join without spaces, so the comma carries the pause. */}
      <span className="sr-only">, opens in a new tab</span>
    </a>
  );
}
