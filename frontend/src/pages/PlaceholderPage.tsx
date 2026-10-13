import type { NavItem } from "@/app/shell/nav";
import { PageHeader } from "@/components/PageHeader";

/** Stands in for a screen until its task builds it. No screen is built before DESIGN.md is
 * approved (T6.1). */
export function PlaceholderPage({ item }: { item: Pick<NavItem, "label" | "description" | "task" | "accent"> }) {
  return (
    <>
      <PageHeader title={item.label} description={item.description} {...(item.accent ? { accent: item.accent } : {})} />
      <div className="px-6 py-6">
        <p className="max-w-[68ch] text-graphite">
          {`Built in ${item.task}, once DESIGN.md is approved.`}
        </p>
      </div>
    </>
  );
}
