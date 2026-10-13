import { PRODUCT_NAME, ACCENT_BORDER, type Accent } from "@/app/shell/nav";
import { cn } from "@/lib/cn";

/** A page's name and one sentence on what it is for. An assistant's header carries its accent as a
 * 4px rule, so the two are never confused (DESIGN.md principle 5). */
export function PageHeader({
  title,
  description,
  accent,
}: {
  title: string;
  description?: string;
  accent?: Accent;
}) {
  return (
    <header
      className={cn(
        "border-b border-rule px-6 py-5",
        accent && cn("border-l-4", ACCENT_BORDER[accent]),
      )}
    >
      <title>{`${title} - ${PRODUCT_NAME}`}</title>
      <h1 className="text-xl font-semibold">{title}</h1>
      {description ? <p className="mt-1 max-w-[68ch] text-base text-graphite">{description}</p> : null}
    </header>
  );
}
