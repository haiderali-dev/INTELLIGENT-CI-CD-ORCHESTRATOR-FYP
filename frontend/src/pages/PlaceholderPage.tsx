import type { NavItem } from "@/app/shell/nav";
import { PageHeader } from "@/components/PageHeader";

/** Stands in for a screen until its task builds it. */
export function PlaceholderPage({ item }: { item: Pick<NavItem, "label" | "description" | "task" | "accent"> }) {
  return (
    <>
      <PageHeader title={item.label} description={item.description} {...(item.accent ? { accent: item.accent } : {})} />
      <div className="px-6 py-6">
        <p className="max-w-[68ch] text-graphite">
          {`This page is built in ${item.task}.`}
        </p>
      </div>
    </>
  );
}
