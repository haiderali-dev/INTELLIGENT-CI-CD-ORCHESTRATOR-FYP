import type { ReactNode } from "react";

import { cn } from "@/lib/cn";
import { MEDIUM_QUERY, useMediaQuery } from "@/lib/useMediaQuery";

export interface Column<T> {
  header: ReactNode;
  cell: (row: T) => ReactNode;
  /** Numbers line up on the right. */
  align?: "right";
  /** Kept on one line, as names and figures are. */
  nowrap?: boolean;
  /** The cell that names the row: a row header in the table, the title of a stacked block. */
  rowHeader?: boolean;
  /** Left out of the stacked block, when the block already says it some other way. */
  stackedHidden?: boolean;
}

// DESIGN.md section 7: 40px rows with a Rule between them, and the first and last columns on the
// page's 24px gutter so the rules still run edge to edge.
const HEAD = "px-2 py-2 text-left text-sm font-semibold text-graphite first:pl-6 last:pr-6";
const CELL = "h-10 px-2 py-2 first:pl-6 last:pr-6";

/**
 * A table from 768 px; below that, one stacked block per row, its name first and every other value
 * as a labelled fact (DESIGN.md sections 7 and 9: no runs of values joined by dots). A table wider
 * than its box scrolls inside it, never the page.
 */
export function DataTable<T>({
  label,
  rows,
  columns,
  rowKey,
  selectedKey = null,
}: {
  /** The table's name for screen readers, such as "Runs, newest first". */
  label: string;
  rows: readonly T[];
  columns: readonly Column<T>[];
  rowKey: (row: T) => string;
  /** The row the page is showing more of, if any. */
  selectedKey?: string | null;
}) {
  const wide = useMediaQuery(MEDIUM_QUERY, true);

  if (!wide) {
    const title = columns.find(({ rowHeader }) => rowHeader);
    const facts = columns.filter((column) => column !== title && !column.stackedHidden);
    return (
      <ul aria-label={label} className="flex flex-col">
        {rows.map((row) => {
          const key = rowKey(row);
          return (
            <li
              key={key}
              className={cn(
                "flex flex-col gap-2 border-b border-rule px-6 py-3",
                key === selectedKey && "bg-ground",
              )}
            >
              {title ? <div className="font-semibold">{title.cell(row)}</div> : null}
              <dl className="flex flex-wrap gap-x-4 gap-y-1 text-sm">
                {facts.map((column, index) => (
                  <div key={index} className="flex min-w-0 gap-1.5">
                    <dt className="shrink-0 text-graphite">{column.header}</dt>
                    {/* A long id or name breaks rather than push the page sideways at 360 px. */}
                    <dd className="min-w-0 tabular-nums wrap-anywhere">{column.cell(row)}</dd>
                  </div>
                ))}
              </dl>
            </li>
          );
        })}
      </ul>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-sm">
        <caption className="sr-only">{label}</caption>
        <thead>
          <tr className="border-b border-rule">
            {columns.map((column, index) => (
              <th
                key={index}
                scope="col"
                className={cn(HEAD, column.align === "right" && "text-right")}
              >
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const key = rowKey(row);
            return (
              <tr
                key={key}
                className={cn(
                  "border-b border-rule hover:bg-ground",
                  key === selectedKey && "bg-ground",
                )}
              >
                {columns.map((column, index) => {
                  const className = cn(
                    CELL,
                    column.align === "right" && "text-right tabular-nums",
                    column.nowrap && "whitespace-nowrap",
                  );
                  return column.rowHeader ? (
                    <th key={index} scope="row" className={cn(className, "text-left font-normal")}>
                      {column.cell(row)}
                    </th>
                  ) : (
                    <td key={index} className={className}>
                      {column.cell(row)}
                    </td>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
