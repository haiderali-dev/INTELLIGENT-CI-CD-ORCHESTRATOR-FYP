import { describe, expect, it } from "vitest";

import { applySuggestion, suggestionsFor, wordAt } from "./composerSuggestions";

const SERVICES = ["payment-service", "auth-service", "payments-ledger"];

describe("composer suggestions", () => {
  it("finds the word that ends at the caret, and none mid-word", () => {
    expect(wordAt("deploy pay", 10)).toEqual({ start: 7, word: "pay" });
    expect(wordAt("deploy pay now", 10)).toEqual({ start: 7, word: "pay" });
    expect(wordAt("deploy payment", 9)).toBeNull();
    expect(wordAt("", 0)).toEqual({ start: 0, word: "" });
  });

  it("offers catalog services from their second letter, case-insensitively", () => {
    expect(suggestionsFor("deploy p", 8, SERVICES)).toEqual([]);
    expect(suggestionsFor("deploy PAY", 10, SERVICES).map(({ value }) => value)).toEqual([
      "payment-service",
      "payments-ledger",
    ]);
    expect(suggestionsFor("deploy auth", 11, SERVICES).map(({ value }) => value)).toEqual([
      "auth-service",
    ]);
    // A finished name needs nothing more.
    expect(suggestionsFor("deploy auth-service", 19, SERVICES)).toEqual([]);
  });

  it("offers the slash commands only at the start of a message", () => {
    expect(suggestionsFor("/", 1, SERVICES).map(({ value }) => value)).toEqual([
      "/status",
      "/rerun",
      "/help",
    ]);
    expect(suggestionsFor("/re", 3, SERVICES)).toEqual([
      { value: "/rerun", hint: "Rerun my last failed tests" },
    ]);
    expect(suggestionsFor("deploy /re", 10, SERVICES)).toEqual([]);
  });

  it("replaces the word with the choice and a space, caret after it", () => {
    expect(applySuggestion("deploy pay", 10, "payment-service")).toEqual({
      text: "deploy payment-service ",
      caret: 23,
    });
    expect(applySuggestion("deploy pay to staging", 10, "payment-service")).toEqual({
      text: "deploy payment-service to staging",
      caret: 22,
    });
  });
});
