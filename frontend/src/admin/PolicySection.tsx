import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";

import { adminApi, adminKeys, type Policy, type RateLimit } from "@/api/adminApi";
import { useApi } from "@/api/apiClientContext";
import { DataTable, type Column } from "@/components/DataTable";
import { Loading, LoadFailed, PageSection } from "@/components/PageStates";

type Rule = Policy["rules"][number];

const RULE_COLUMNS: readonly Column<Rule>[] = [
  { header: "Rule", rowHeader: true, cell: ({ rule }) => rule },
  { header: "Developer", cell: ({ developer }) => developer },
  { header: "DevOps", cell: ({ devops }) => devops },
  { header: "Admin", cell: ({ admin }) => admin },
];

/** "5 a minute", or "30 every 2 minutes" for a period that is not a whole minute. */
function rateText({ capacity, per_seconds: seconds }: RateLimit): string {
  if (seconds === 60) {
    return `${String(capacity)} a minute`;
  }
  if (seconds % 60 === 0) {
    return `${String(capacity)} every ${String(seconds / 60)} minutes`;
  }
  return `${String(capacity)} every ${String(seconds)} seconds`;
}

const LIMIT_COLUMNS: readonly Column<RateLimit>[] = [
  {
    header: "Counted for",
    rowHeader: true,
    // The backend's phrases are sentence fragments; standing alone in a cell, each starts a sentence.
    cell: ({ applies_to: appliesTo }) => appliesTo.charAt(0).toUpperCase() + appliesTo.slice(1),
  },
  { header: "Allowed", nowrap: true, cell: (limit) => rateText(limit) },
];

/**
 * The HIGH quota and 4.5.5's rules, as the backend enforces them. They are code and configuration,
 * which the API reports and cannot change (`editable: false`), so nothing here is a control.
 */
export function PolicySection() {
  const api = useApi(adminApi);
  const policy = useQuery({ queryKey: adminKeys.policy, queryFn: () => api.policy() });
  const limits = useQuery({ queryKey: adminKeys.limits, queryFn: () => api.limits() });

  let body: ReactNode;
  if (policy.data) {
    const { high_urgency_daily_quota: quota, production_enabled: production, rules, editable } =
      policy.data;
    body = (
      <>
        <dl className="flex flex-wrap gap-x-10 gap-y-3 px-6">
          <div className="flex flex-col gap-0.5">
            <dt className="text-sm text-graphite">HIGH urgency</dt>
            <dd>
              <span className="text-xl font-semibold tabular-nums">{quota}</span>
              <span>{` a day for each Developer, then MEDIUM`}</span>
            </dd>
          </div>
          <div className="flex flex-col gap-0.5">
            <dt className="text-sm text-graphite">Production deploys</dt>
            <dd className="text-xl font-semibold">{production ? "Allowed" : "Refused"}</dd>
          </div>
        </dl>
        <DataTable label="Rules in force, by role" rows={rules} columns={RULE_COLUMNS} rowKey={({ rule }) => rule} />
        {editable ? null : (
          <p className="max-w-[68ch] px-6 text-sm text-graphite">
            These rules are code and the quota is configuration (HIGH_URGENCY_DAILY_QUOTA), so this
            page shows them and cannot change them.
          </p>
        )}
      </>
    );
  } else if (policy.isError) {
    body = (
      <LoadFailed
        what="The policy"
        error={policy.error}
        onRetry={() => {
          void policy.refetch();
        }}
      />
    );
  } else {
    body = <Loading>Loading the policy</Loading>;
  }

  let limitsBody: ReactNode;
  if (limits.data) {
    limitsBody = (
      <DataTable
        label="Rate limits"
        rows={limits.data}
        columns={LIMIT_COLUMNS}
        rowKey={({ name }) => name}
      />
    );
  } else if (limits.isError) {
    limitsBody = (
      <LoadFailed
        what="The rate limits"
        error={limits.error}
        onRetry={() => {
          void limits.refetch();
        }}
      />
    );
  } else {
    limitsBody = <Loading>Loading the rate limits</Loading>;
  }

  return (
    <PageSection title="Policy" className="border-t border-rule">
      {body}
      <h3 className="px-6 pt-2 font-semibold">Rate limits</h3>
      {limitsBody}
      <p className="max-w-[68ch] px-6 text-sm text-graphite">
        Over a limit, a request is refused and told how long to wait. The limits are code
        (app/core/ratelimit.py), read from there, so this list is what the backend enforces.
      </p>
    </PageSection>
  );
}
