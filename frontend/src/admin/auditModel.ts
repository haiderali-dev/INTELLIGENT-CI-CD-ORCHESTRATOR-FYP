/**
 * An audit entry's details in words. The backend stores what changed as JSON, for example
 * `{"active": {"from": true, "to": false}}`; the page shows "active: true to false".
 */

function isChange(value: unknown): value is { from: unknown; to: unknown } {
  return typeof value === "object" && value !== null && "from" in value && "to" in value;
}

function describe(value: unknown): string {
  if (isChange(value)) {
    return `${describe(value.from)} to ${describe(value.to)}`;
  }
  if (Array.isArray(value)) {
    return value.map(describe).join(", ");
  }
  if (value === null || value === undefined) {
    return "none";
  }
  if (typeof value === "string") {
    return value;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return JSON.stringify(value);
}

export function describeDetails(details: Readonly<Record<string, unknown>>): string {
  return Object.entries(details)
    .map(([key, value]) => `${key}: ${describe(value)}`)
    .join("; ");
}
