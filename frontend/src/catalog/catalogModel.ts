/** "security_scan" as "Security scan": the catalog's names, readable. */
export function readable(name: string): string {
  const words = name.replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** A service's test suites in words: "unit, about 8s; integration, about 20s". */
export function describeSuites(
  suites: readonly { name: string; approx_seconds: number }[],
): string {
  if (suites.length === 0) {
    return "None";
  }
  return suites.map(({ name, approx_seconds: seconds }) => `${name}, about ${String(seconds)}s`).join("; ");
}

/** A repository's branches in words, the default one marked. */
export function describeBranches(branches: readonly string[], defaultBranch: string): string {
  if (branches.length === 0) {
    return "No branches yet.";
  }
  const names = branches.map((name) => (name === defaultBranch ? `${name} (default)` : name));
  return `${String(branches.length)} ${branches.length === 1 ? "branch" : "branches"}: ${names.join(", ")}`;
}
