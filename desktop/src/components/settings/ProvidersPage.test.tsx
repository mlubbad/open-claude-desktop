// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ProvidersPage } from "./ProvidersPage";

const OLLAMA = {
  id: "ollama", label: "Ollama", is_local: true, requires_key: false, has_key: false,
  default_model: "llama3.1", models: ["llama3.1", "llama3.2"], docs: "", is_default: false,
};
const stored: { custom_models: Record<string, string[]>; hidden_models: Record<string, string[]>; visible_models: Record<string, string[]> } = {
  custom_models: {}, hidden_models: {}, visible_models: {},
};
const saveSpy = vi.fn(async (patch: object) => ({ ...patch }));
const available: { ok: boolean; models: string[]; detail?: string } = { ok: true, models: [] };

vi.mock("../../api/client", () => ({
  providers: {
    list: vi.fn(async () => [{ ...OLLAMA }]),
    test: vi.fn(),
    setKey: vi.fn(),
    deleteKey: vi.fn(async () => ({ id: "vertex", has_key: false })),
    availableModels: vi.fn(async () => ({ id: "ollama", ...available })),
  },
  settings: { get: vi.fn(async () => ({ ...stored })), save: (p: object) => saveSpy(p) },
}));

const noop = () => {};
const active = { provider: "ollama", model: "llama3.1" };

describe("ProvidersPage — custom models", () => {
  beforeEach(() => {
    saveSpy.mockClear();
    stored.custom_models = {};
    stored.hidden_models = {};
    stored.visible_models = {};
    available.ok = true;
    available.models = [];
  });

  it("shows the built-in catalog chips", async () => {
    render(<ProvidersPage active={active} onPick={noop} />);
    expect(await screen.findByRole("button", { name: "llama3.1" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "llama3.2" })).toBeInTheDocument();
  });

  it("shows a loading spinner until the providers resolve, then hides it", async () => {
    render(<ProvidersPage active={active} onPick={noop} />);
    expect(screen.getByText(/Loading providers/i)).toBeInTheDocument();
    await screen.findByRole("button", { name: "llama3.1" });
    expect(screen.queryByText(/Loading providers/i)).not.toBeInTheDocument();
  });

  it("adding a model persists it under custom_models", async () => {
    render(<ProvidersPage active={active} onPick={noop} />);
    const input = await screen.findByLabelText("Add a custom model to Ollama");
    fireEvent.change(input, { target: { value: "qwen2.5:14b" } });
    fireEvent.click(screen.getByRole("button", { name: "Add model to Ollama" }));
    await waitFor(() =>
      expect(saveSpy).toHaveBeenCalledWith(
        expect.objectContaining({ custom_models: { ollama: ["qwen2.5:14b"] } }),
      ));
    // It appears as a chip (custom-first), immediately usable.
    expect(await screen.findByRole("button", { name: "qwen2.5:14b" })).toBeInTheDocument();
  });

  it("removing a built-in model hides it (not deleted from the shipped catalog)", async () => {
    render(<ProvidersPage active={active} onPick={noop} />);
    await screen.findByRole("button", { name: "llama3.1" });
    fireEvent.click(screen.getByRole("button", { name: "Remove llama3.2 from Ollama" }));
    await waitFor(() =>
      expect(saveSpy).toHaveBeenCalledWith(
        expect.objectContaining({ hidden_models: { ollama: ["llama3.2"] } }),
      ));
  });

  it("removing a custom model deletes it from custom_models", async () => {
    stored.custom_models = { ollama: ["my-model"] };
    render(<ProvidersPage active={active} onPick={noop} />);
    fireEvent.click(await screen.findByRole("button", { name: "Remove my-model from Ollama" }));
    await waitFor(() =>
      expect(saveSpy).toHaveBeenCalledWith(
        expect.objectContaining({ custom_models: { ollama: [] } }),
      ));
  });

  it("does not add a blank model name", async () => {
    render(<ProvidersPage active={active} onPick={noop} />);
    const addBtn = await screen.findByRole("button", { name: "Add model to Ollama" });
    expect(addBtn).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Add a custom model to Ollama"), { target: { value: "   " } });
    expect(addBtn).toBeDisabled();
  });

  it("Load models merges the provider's live catalog into custom_models", async () => {
    available.models = ["llama3.1", "brand-new-model"]; // one existing, one new
    render(<ProvidersPage active={active} onPick={noop} />);
    fireEvent.click(await screen.findByRole("button", { name: /Load models/i }));
    await waitFor(() =>
      expect(saveSpy).toHaveBeenCalledWith(
        expect.objectContaining({ custom_models: { ollama: ["brand-new-model"] } }),
      ));
    // Only the genuinely new id is added; the existing built-in isn't duplicated.
    expect(await screen.findByRole("button", { name: "brand-new-model" })).toBeInTheDocument();
  });
});

// Key-OPTIONAL providers (Vertex AI): usable without a key via cloud auth (ADC),
// with the key box repurposed as an optional short-lived-token override.
describe("ProvidersPage — key-optional providers", () => {
  const VERTEX = {
    id: "vertex", label: "Vertex AI", is_local: false, requires_key: false,
    key_optional: true, key_hint: "Uses Google Cloud ADC; pasting a token overrides it.",
    has_key: false, default_model: "google/gemini-3.5-flash",
    models: ["google/gemini-3.5-flash"], docs: "", is_default: false,
  };

  beforeEach(async () => {
    stored.custom_models = {};
    stored.hidden_models = {};
    stored.visible_models = {};
    const { providers } = await import("../../api/client");
    vi.mocked(providers.list).mockResolvedValue([{ ...VERTEX }]);
    vi.mocked(providers.deleteKey).mockClear();
  });

  it("renders the optional token box, setup hint, and cloud-auth badge", async () => {
    render(<ProvidersPage active={active} onPick={noop} />);
    expect(
      await screen.findByLabelText("Vertex AI access token (optional)"),
    ).toBeInTheDocument();
    expect(screen.getByText(/Uses Google Cloud ADC/)).toBeInTheDocument();
    expect(screen.getByText("cloud auth")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Clear/ })).not.toBeInTheDocument();
    // Usable without a key: Test / Load models / model picks are all enabled.
    expect(screen.getByRole("button", { name: "Test" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "google/gemini-3.5-flash" })).toBeEnabled();
  });

  it("with a stored token shows 'token set' and Clear returns to ADC", async () => {
    const { providers } = await import("../../api/client");
    vi.mocked(providers.list).mockResolvedValue([{ ...VERTEX, has_key: true }]);
    render(<ProvidersPage active={active} onPick={noop} />);
    expect(await screen.findByText("token set")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Clear" }));
    await waitFor(() => expect(providers.deleteKey).toHaveBeenCalledWith("vertex"));
  });
});
