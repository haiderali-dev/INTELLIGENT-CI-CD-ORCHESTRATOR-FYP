import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";

import { adminApi, adminKeys, type Policy } from "@/api/adminApi";
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

/**
 * The HIGH quota and 4.5.5's rules, as the backend enforces them. They are code and configuration,
 * which the API reports and cannot change (`editable: false`), so nothing here is a control.
 */
export function PolicySection() {
  const api = useApi(adminApi);
  const policy = useQuery({ queryKey: adminKeys.policy, queryFn: () => api.policy() });

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

  return (
    <PageSection title="Policy" className="border-t border-rule">
      {body}
    </PageSection>
  );
}
