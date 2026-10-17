import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import CodeView from "./CodeView";
import { YAML_SYNTAX_MESSAGE } from "./diagnostics";

const SPEC = "version: 1\nservice: payment-service\nbranch: main\n";

describe("CodeView", () => {
  it("shows read-only code that can still be focused and read", () => {
    render(<CodeView label="Jenkinsfile" language="groovy" value={"pipeline {\n  agent any\n}\n"} />);

    const code = screen.getByRole("textbox", { name: "Jenkinsfile" });
    expect(code).toHaveAttribute("contenteditable", "false");
    expect(code).toHaveAttribute("aria-readonly", "true");
    expect(code).toHaveAttribute("tabindex", "0");
    expect(code).toHaveTextContent("agent any");
  });

  it("lets the spec be edited", () => {
    render(<CodeView label="Spec" language="yaml" value={SPEC} onChange={vi.fn()} />);

    const code = screen.getByRole("textbox", { name: "Spec" });
    expect(code).toHaveAttribute("contenteditable", "true");
    expect(code).toHaveTextContent("service: payment-service");
  });

  it("follows new text from outside, such as a regenerated spec", () => {
    const { rerender } = render(<CodeView label="Spec" language="yaml" value={SPEC} onChange={vi.fn()} />);

    rerender(
      <CodeView label="Spec" language="yaml" value={SPEC.replace("main", "release")} onChange={vi.fn()} />,
    );

    expect(screen.getByRole("textbox", { name: "Spec" })).toHaveTextContent("branch: release");
  });

  it("lists the backend's problems by line, and YAML's own", () => {
    render(
      <CodeView
        label="Spec"
        language="yaml"
        value={"version: 2\nservice: payment-service\n  branch: main\n"}
        onChange={vi.fn()}
        diagnostics={[{ line: 1, message: "version: must be 1." }]}
      />,
    );

    const list = screen.getByRole("list", { name: "Problems in Spec" });
    const items = within(list).getAllByRole("listitem");
    expect(items.map((item) => item.textContent)).toEqual([
      "Line 1 version: must be 1.",
      `Line 3 ${YAML_SYNTAX_MESSAGE}`,
    ]);
  });

  it("lists nothing for read-only code", () => {
    render(
      <CodeView
        label="config.xml"
        language="xml"
        value="<project><broken></project>"
        diagnostics={[{ line: 1, message: "ignored" }]}
      />,
    );

    expect(screen.queryByRole("list")).toBeNull();
  });

  it("shows what a regenerate changed", () => {
    const { container } = render(
      <CodeView
        label="Spec"
        language="yaml"
        value={SPEC.replace("main", "release")}
        previous={SPEC}
        onChange={vi.fn()}
      />,
    );

    expect(container.querySelector(".cm-editor")).toHaveClass("cm-merge-b");
    expect(container.querySelector(".cm-deletedChunk")).toHaveTextContent("branch: main");
  });
});
