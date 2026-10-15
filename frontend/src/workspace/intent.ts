import type { components } from "@/api/schema";

type Intent = components["schemas"]["Intent"];


/** The urgency levels, in capitals as the data, the report and 4.7.4's approval sentence write
 * them (DESIGN.md section 3). Checked against the API's own list. */
export const URGENCIES = ["HIGH", "MEDIUM", "LOW"] as const satisfies readonly NonNullable<
  Intent["urgency"]
>[];
export type Urgency = (typeof URGENCIES)[number];

/** What the intent card shows: the four fields 4.7.4 names, from the API's intent (D-058). A
 * field the request does not need is null. */
export type IntentFields = Pick<Intent, "service" | "branch" | "environment" | "urgency">;

/** The actions that generate jobs; the others (status, re-run, cancel) are answered in words. */
export const GENERATING_ACTIONS: ReadonlySet<Intent["action"]> = new Set([
  "BUILD",
  "TEST",
  "DEPLOY",
  "BUILD_TEST_DEPLOY",
]);

/** The card's four fields from a record. A branch the user did not name is the one the backend
 * resolved in Git, which is what the generated jobs will use. */
export function intentFields(record: components["schemas"]["IntentRecord"]): IntentFields {
  const { intent, resolved } = record;
  return {
    service: intent.service,
    branch: intent.branch ?? resolved.branch,
    environment: intent.environment,
    urgency: intent.urgency,
  };
}
