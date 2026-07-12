// @vitest-environment jsdom
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("../../api/client", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  mcp: {
    directory: vi.fn(async () => [
      { id: "fetch", name: "Fetch", description: "Fetch web pages as markdown.",
        transport: "stdio", command: "uvx", args: ["mcp-server-fetch"],
        env_keys: [], runtime: "python", tags: ["web", "official"] },
    ]),
  },
}));

import type { McpServer } from "../../api/client";
import { ConnectorsPage } from "./ConnectorsPage";
import type { ConnectorControls } from "./types";

function server(over: Partial<McpServer>): McpServer {
  return {
    id: "playwright",
    name: "playwright",
    transport: "stdio",
    command: "npx",
    args: ["@playwright/mcp@latest"],
    url: "",
    auth: false,
    source: "",
    status: "error",
    detail: "connection timed out after 90s",
    tool_count: 0,
    ...over,
  } as McpServer;
}

function makeControls(over: Partial<ConnectorControls> = {}): ConnectorControls {
  return {
    servers: [server({})],
    enabled: [],
    err: null,
    onAdd: vi.fn(),
    onInstall: vi.fn(),
    onAddOAuth: vi.fn(),
    onAuthorize: vi.fn(),
    onRemove: vi.fn(),
    onToggle: vi.fn(),
    onRetry: vi.fn(),
    retrying: null,
    ...over,
  };
}

describe("ConnectorsPage error card", () => {
  it("shows the error detail and a Retry button; Retry calls onRetry(sid)", () => {
    const c = makeControls();
    render(<ConnectorsPage c={c} />);
    expect(screen.getByText(/connection timed out after 90s/)).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Retry playwright"));
    expect(c.onRetry).toHaveBeenCalledWith("playwright");
  });

  it("shows Retrying… (disabled) while the re-connect is in flight", () => {
    render(<ConnectorsPage c={makeControls({ retrying: "playwright" })} />);
    const btn = screen.getByLabelText("Retry playwright");
    expect(btn).toBeDisabled();
    expect(btn).toHaveTextContent("Retrying…");
  });

  it("offers no Retry on a connected server", () => {
    const c = makeControls({
      servers: [server({ status: "connected", detail: "3 tools", tool_count: 3 })],
    });
    render(<ConnectorsPage c={c} />);
    expect(screen.queryByLabelText("Retry playwright")).toBeNull();
  });
});

describe("connector directory (P1-3)", () => {
  it("Browse lists catalog entries and Use PREFILLS the add form (no silent add)", async () => {
    const c = makeControls();
    render(<ConnectorsPage c={c} />);
    fireEvent.click(screen.getByText("Browse"));
    expect(await screen.findByText("Fetch")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Use" }));
    // The add form opens on the Local tab with the entry's command/args filled in.
    expect(screen.getByLabelText("Connector name")).toHaveValue("Fetch");
    expect(screen.getByPlaceholderText("Command (e.g. npx, uv)")).toHaveValue("uvx");
    expect(screen.getByLabelText("Command arguments")).toHaveValue("mcp-server-fetch");
    // Nothing was added yet — the user must confirm.
    expect(c.onAdd).not.toHaveBeenCalled();
  });
});
