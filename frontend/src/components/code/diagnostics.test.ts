import { describe, expect, it } from "vitest";

import { lineAt, yamlSyntaxErrors, YAML_SYNTAX_MESSAGE } from "./diagnostics";

describe("YAML syntax errors", () => {
  it("finds none in a valid spec", () => {
    expect(yamlSyntaxErrors("version: 1\nservice: payment-service\nstages:\n  - build\n")).toEqual([]);
  });

  it("names the line a structural mistake is on, once per line", () => {
    expect(yamlSyntaxErrors("version: 1\nservice: payment-service\n  branch: main\n")).toEqual([
      { line: 3, message: YAML_SYNTAX_MESSAGE },
    ]);
    expect(yamlSyntaxErrors("version: 1\nstages: [build\n")).toEqual([
      { line: 2, message: YAML_SYNTAX_MESSAGE },
    ]);
    expect(yamlSyntaxErrors("jobs:\n  - build\n -test\n")).toEqual([
      { line: 3, message: YAML_SYNTAX_MESSAGE },
    ]);
  });

  it("leaves to the backend what the grammar lets through", () => {
    // The backend's spec check finds these; the editor shows them from its diagnostics.
    expect(yamlSyntaxErrors('version: 1\nservice: "payment-service\n')).toEqual([]);
  });

  it("counts lines from 1", () => {
    expect([lineAt("a\nb\nc", 0), lineAt("a\nb\nc", 2), lineAt("a\nb\nc", 4)]).toEqual([1, 2, 3]);
  });
});
