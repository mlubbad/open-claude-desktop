// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const PROVIDERS = [
  { id: "anthropic", label: "Anthropic", is_local: false, requires_key: true, has_key: true, default_model: "claude-opus", models: ["claude-opus", "claude-sonnet"], docs: "", is_default: true },
  // Remote provider with no key on file — must be filtered out (a pick would just error).
  { id: "openai", label: "OpenAI", is_local: false, requires_key: true, has_key: false, default_model: "gpt-4o", models: ["gpt-4o"], docs: "", is_default: false },
  // Local provider needs no key — always offered.
  { id: "ollama", label: "Ollama", is_local: true, requires_key: false, has_key: false, default_model: "llama3", models: ["llama3"], docs: "", is_default: false },
];

vi.mock("../api/client", () => ({
  providers: { list: vi.fn(async () => PROVIDERS) },
  settings: { get: vi.fn(async () => ({ visible_models: {} })) },
}));

import { RetryModelMenu } from "./RetryModelMenu";

describe("RetryModelMenu", () => {
  beforeEach(() => vi.clearAllMocks());

  it("offers only usable providers and marks the current model", async () => {
    render(
      <RetryModelMenu current={{ provider: "anthropic", model: "claude-opus" }} onPick={() => {}} onClose={() => {}} />,
    );
    await waitFor(() => expect(screen.getByText("Anthropic")).toBeInTheDocument());
    expect(screen.getByText("Ollama")).toBeInTheDocument(); // local → offered
    expect(screen.queryByText("OpenAI")).not.toBeInTheDocument(); // keyless remote → hidden

    // The current model's row is marked active (has the checkmark / active class).
    const cur = screen.getByText("claude-opus").closest("button")!;
    expect(cur.className).toContain("active");
  });

  it("regenerates with the picked model+provider", async () => {
    const onPick = vi.fn();
    render(
      <RetryModelMenu current={{ provider: "anthropic", model: "claude-opus" }} onPick={onPick} onClose={() => {}} />,
    );
    await waitFor(() => expect(screen.getByText("claude-sonnet")).toBeInTheDocument());
    fireEvent.click(screen.getByText("claude-sonnet"));
    expect(onPick).toHaveBeenCalledWith("anthropic", "claude-sonnet");
  });
});
