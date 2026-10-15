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
