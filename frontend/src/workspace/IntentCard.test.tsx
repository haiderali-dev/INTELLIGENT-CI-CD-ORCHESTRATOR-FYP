import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { components } from "@/api/schema";

import type { IntentFields } from "./intent";
import { IntentCard } from "./IntentCard";

type Service = components["schemas"]["ServiceResponse"];

const SERVICES: Service[] = [
  {
    name: "payment-service",
    repo: "https://github.com/haiderali-dev/payment-service",
    default_branch: "main",
    agent_label: "linux",
    test_suites: [],
    allowed_environments: ["staging"],
    extra_stages: [],
  },
  {
    name: "auth-service",
    repo: "https://github.com/haiderali-dev/auth-service",
    default_branch: "develop",
    agent_label: "linux",
    test_suites: [],
    allowed_environments: ["staging", "qa"],
    extra_stages: [],
  },
];

const INTENT: IntentFields = {
  service: "payment-service",
  branch: "main",
  environment: "staging",
  urgency: "MEDIUM",
};

function renderCard(props: Partial<Parameters<typeof IntentCard>[0]> = {}) {
  const onGenerate = vi.fn();
  const onEdit = vi.fn();
  render(
    <IntentCard
      intent={INTENT}
      services={SERVICES}
      branches={{ "payment-service": ["main", "feature/refund"] }}
      onGenerate={onGenerate}
      onEdit={onEdit}
      {...props}
    />,
  );
  return { onGenerate, onEdit };
}

const options = (label: string) =>
  within(screen.getByLabelText(label)).getAllByRole("option").map((option) => option.textContent);

describe("IntentCard", () => {
  it("shows the four fields as labelled chips", () => {
    renderCard({ intent: { ...INTENT, environment: null } });

    const card = screen.getByRole("region", { name: "Intent" });
    const terms = within(card).getAllByRole("term").map((term) => term.textContent);
    const values = within(card).getAllByRole("definition").map((value) => value.textContent);
    expect(terms).toEqual(["Service", "Branch", "Environment", "Urgency"]);
    expect(values).toEqual(["payment-service", "main", "Not set", "MEDIUM"]);
  });

  it("generates on request, and once only while it is generating", async () => {
    const user = userEvent.setup();
    const { onGenerate } = renderCard();
    await user.click(screen.getByRole("button", { name: "Generate" }));
    expect(onGenerate).toHaveBeenCalledOnce();
  });

  it("does not generate twice", async () => {
    const user = userEvent.setup();
    const { onGenerate } = renderCard({ generating: true });

    const button = screen.getByRole("button", { name: "Generating" });
    expect(button).toHaveAttribute("aria-disabled", "true");
    await user.click(button);
    expect(onGenerate).not.toHaveBeenCalled();
  });

  it("offers only catalog values when editing, and never production", async () => {
    const user = userEvent.setup();
    renderCard();

    await user.click(screen.getByRole("button", { name: "Edit" }));

    expect(options("Service")).toEqual(["payment-service", "auth-service"]);
    expect(options("Branch")).toEqual(["main", "feature/refund"]);
    expect(options("Environment")).toEqual(["Not set", "staging"]);
    expect(options("Urgency")).toEqual(["HIGH", "MEDIUM", "LOW"]);
    expect(screen.queryByRole("option", { name: /production/i })).toBeNull();
  });

  it("moves to the new service's own branches and environments", async () => {
    const user = userEvent.setup();
    renderCard();
    await user.click(screen.getByRole("button", { name: "Edit" }));

    await user.selectOptions(screen.getByLabelText("Service"), "auth-service");

    // auth-service has no branch list yet, so its default branch is offered.
    expect(options("Branch")).toEqual(["develop"]);
    expect(screen.getByLabelText("Branch")).toHaveValue("develop");
    expect(options("Environment")).toEqual(["Not set", "staging", "qa"]);
    expect(screen.getByLabelText("Environment")).toHaveValue("staging");
  });

  it("sends only what changed", async () => {
    const user = userEvent.setup();
    const { onEdit } = renderCard();
    await user.click(screen.getByRole("button", { name: "Edit" }));

    await user.selectOptions(screen.getByLabelText("Urgency"), "HIGH");
    await user.selectOptions(screen.getByLabelText("Branch"), "feature/refund");
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    expect(onEdit).toHaveBeenCalledWith({ urgency: "HIGH", branch: "feature/refund" });
    expect(screen.getByRole("button", { name: "Generate" })).toBeInTheDocument();
  });

  it("sends nothing when nothing changed, and Cancel changes nothing", async () => {
    const user = userEvent.setup();
    const { onEdit } = renderCard();

    await user.click(screen.getByRole("button", { name: "Edit" }));
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    await user.click(screen.getByRole("button", { name: "Edit" }));
    await user.selectOptions(screen.getByLabelText("Urgency"), "LOW");
    await user.click(screen.getByRole("button", { name: "Cancel" }));

    expect(onEdit).not.toHaveBeenCalled();
    expect(screen.getByText("MEDIUM")).toBeInTheDocument();
  });
});
