import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { Clarification } from "./Clarification";

describe("Clarification", () => {
  it("asks the question with at most four answers to click", async () => {
    const user = userEvent.setup();
    const onAnswer = vi.fn();
    render(
      <Clarification
        question="Which service should I test?"
        options={["payment-service", "auth-service", "ledger", "gateway", "search", "mail"]}
        onAnswer={onAnswer}
      />,
    );

    expect(screen.getByText("Which service should I test?")).toBeInTheDocument();
    const answers = within(screen.getByRole("group", { name: "Answers" })).getAllByRole("button");
    expect(answers.map((answer) => answer.textContent)).toEqual([
      "payment-service",
      "auth-service",
      "ledger",
      "gateway",
    ]);
    expect(screen.getByText("Or type a different answer below.")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "auth-service" }));
    expect(onAnswer).toHaveBeenCalledWith("auth-service");
  });

  it("takes no answer while one is being sent", async () => {
    const user = userEvent.setup();
    const onAnswer = vi.fn();
    render(<Clarification question="Which suite?" options={["unit"]} onAnswer={onAnswer} disabled />);

    await user.click(screen.getByRole("button", { name: "unit" }));
    expect(onAnswer).not.toHaveBeenCalled();
  });

  it("asks for a typed answer when there is nothing to click", () => {
    render(<Clarification question="Why is this urgent?" options={[]} onAnswer={vi.fn()} />);

    expect(screen.queryByRole("group")).toBeNull();
    expect(screen.getByText("Type your answer below.")).toBeInTheDocument();
  });
});
