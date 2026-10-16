import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

import { adminApi, adminKeys, type AuditEntry } from "@/api/adminApi";
import { useApi } from "@/api/apiClientContext";
import { button } from "@/components/button";
import { DataTable, type Column } from "@/components/DataTable";
import { Empty, Loading, LoadFailed, PageSection } from "@/components/PageStates";
import { cn } from "@/lib/cn";
import { formatWhen, parseApiTime } from "@/lib/format";

import { describeDetails } from "./auditModel";

export const AUDIT_PAGE = 50;

const COLUMNS: readonly Column<AuditEntry>[] = [
  {
    header: "When",
    nowrap: true,
    cell: ({ created_at: created }) => formatWhen(parseApiTime(created)),
  },
  {
    header: "Who",
    nowrap: true,
    // No actor: the system acted, such as a chain expiring.
    cell: ({ actor_email: email }) => email ?? "The system",
  },
  { header: "Action", rowHeader: true, nowrap: true, cell: ({ action }) => action },
  // A target is a name or an id: kept whole on one line, as job names are everywhere else.
  { header: "Target", nowrap: true, cell: ({ target }) => target },
  {
    header: "Details",
    // Details carry long ids and JSON, which may break anywhere rather than widen the table.
    cell: ({ details }) => (
      <span className="wrap-anywhere text-graphite">{describeDetails(details)}</span>
    ),
  },
];

/** Every approval, job creation, HIGH request, policy denial and admin change (4.4.3), newest
 * first, a page at a time. */
export function AuditSection() {
  const api = useApi(adminApi);
  const [offset, setOffset] = useState(0);
  const audit = useQuery({
    queryKey: adminKeys.audit(offset),
    queryFn: () => api.audit(AUDIT_PAGE, offset),
    placeholderData: keepPreviousData,
  });

  let body: ReactNode;
  if (audit.data) {
    const { items, total } = audit.data;
    const first = total === 0 ? 0 : offset + 1;
    const last = offset + items.length;
    body =
      total === 0 ? (
        <Empty>
          <p>Nothing has been recorded yet. Approvals, new jobs and admin changes appear here.</p>
        </Empty>
      ) : (
        <>
          <DataTable label="Audit log, newest first" rows={items} columns={COLUMNS} rowKey={({ id }) => id} />
          <div className="flex flex-wrap items-center gap-3 px-6">
            <p aria-live="polite" className="text-sm text-graphite tabular-nums">
              {`Entries ${String(first)} to ${String(last)} of ${String(total)}`}
            </p>
            <button
              type="button"
              aria-disabled={offset === 0}
              onClick={() => {
                if (offset > 0) {
                  setOffset(Math.max(0, offset - AUDIT_PAGE));
                }
              }}
              className={cn(button(), "h-8 px-3 text-sm max-md:h-11")}
            >
              Newer
            </button>
            <button
              type="button"
              aria-disabled={last >= total}
              onClick={() => {
                if (last < total) {
                  setOffset(offset + AUDIT_PAGE);
                }
              }}
              className={cn(button(), "h-8 px-3 text-sm max-md:h-11")}
            >
              Older
            </button>
          </div>
        </>
      );
  } else if (audit.isError) {
    body = (
      <LoadFailed
        what="The audit log"
        error={audit.error}
        onRetry={() => {
          void audit.refetch();
        }}
      />
    );
  } else {
    body = <Loading>Loading the audit log</Loading>;
  }

  return (
    <PageSection title="Audit log" className="border-t border-rule">
      {body}
    </PageSection>
  );
}
