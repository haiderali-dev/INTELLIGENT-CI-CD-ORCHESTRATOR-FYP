/** The urgency levels, in capitals as the data, the report and 4.7.4's approval sentence write
 * them (DESIGN.md section 3). */
export const URGENCIES = ["HIGH", "MEDIUM", "LOW"] as const;
export type Urgency = (typeof URGENCIES)[number];

/** What the intent card shows: the four fields 4.7.4 names. A field the request does not need is
 * null. */
export interface IntentFields {
  service: string | null;
  branch: string | null;
  environment: string | null;
  urgency: Urgency | null;
}
