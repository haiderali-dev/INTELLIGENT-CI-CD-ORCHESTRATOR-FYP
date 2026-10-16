import { describe, expect, it } from "vitest";

import { roleLabel, isAdmin } from "@/auth/roles";
import { describeBranches, describeSuites, readable } from "@/catalog/catalogModel";
import * as captured from "@/test/fixtures/pages";

import { describeDetails } from "./auditModel";

describe("audit details", () => {
  it("words each kind of value the backend stores", () => {
    const [updated, created, , , approved] = captured.audit.items;

    expect(updated && describeDetails(updated.details)).toBe("active: true to false");
    expect(created && describeDetails(created.details)).toBe("role: DEVOPS");
    expect(approved && describeDetails(approved.details)).toMatch(
      /^command_id: \w+; chain_id: \w+; jobs: pl-payment-service-build-test-deploy-staging/,
    );
    expect(describeDetails({ reason: null, nested: { a: 1 } })).toBe('reason: none; nested: {"a":1}');
    expect(describeDetails({})).toBe("");
  });
});

describe("the catalog's words", () => {
  it("makes the catalog's names readable", () => {
    expect(readable("security_scan")).toBe("Security scan");
    expect(readable("staging")).toBe("Staging");
  });

  it("describes suites and branches, marking the default", () => {
    const [payment] = captured.services.items;

    expect(payment && describeSuites(payment.test_suites)).toBe(
      "unit, about 8s; integration, about 20s",
    );
    expect(describeSuites([])).toBe("None");
    expect(describeBranches(captured.branchesPayment.branches, "main")).toBe(
      "2 branches: demo/failing-tests, main (default)",
    );
    expect(describeBranches([], "main")).toBe("No branches yet.");
  });
});

describe("roles", () => {
  it("names each role, and shows one it does not know as sent", () => {
    expect(captured.roles.map(roleLabel)).toEqual(["Developer", "DevOps", "Admin"]);
    expect(roleLabel("AUDITOR")).toBe("AUDITOR");
  });

  it("offers Admin work only to an Admin", () => {
    expect(isAdmin(captured.me)).toBe(true);
    expect(isAdmin({ role: "DEVOPS" })).toBe(false);
    expect(isAdmin(null)).toBe(false);
  });
});
