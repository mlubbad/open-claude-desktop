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
    tools: [],
    disabled_tools: [],
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
    onToolToggle: vi.fn(),
    updates: {},
    updating: null,
    onCheckUpdate: vi.fn(),
    onUpdate: vi.fn(),
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

describe("extension updates (P1-13)", () => {
  const ext = () =>
    server({ status: "connected", source: "mcpb", version: "1.0.0",
             repository: "https://github.com/acme/ext" });

  it("offers Check for updates on extensions with a repository", () => {
    const c = makeControls({ servers: [ext()] });
    render(<ConnectorsPage c={c} />);
    fireEvent.click(screen.getByLabelText("Check updates for playwright"));
    expect(c.onCheckUpdate).toHaveBeenCalledWith("playwright");
  });

  it("shows Update to vX once a newer release is known", () => {
    const c = makeControls({
      servers: [ext()],
      updates: { playwright: { current: "1.0.0", latest: "2.0.0", url: "u", notes: "" } },
    });
    render(<ConnectorsPage c={c} />);
    fireEvent.click(screen.getByLabelText("Update playwright"));
    expect(c.onUpdate).toHaveBeenCalledWith("playwright");
  });

  it("offers no update button on plain connectors", () => {
    render(<ConnectorsPage c={makeControls()} />);
    expect(screen.queryByLabelText("Check updates for playwright")).toBeNull();
  });
});

describe("per-tool toggles (P1-12)", () => {
  it("expands a connector's tool list and toggles one tool off", () => {
    const c = makeControls({
      servers: [server({ status: "connected", tool_count: 2,
                         tools: ["read_file", "delete_file"], disabled_tools: ["delete_file"] })],
    });
    render(<ConnectorsPage c={c} />);
    // Collapsed summary shows the on/off count.
    fireEvent.click(screen.getByRole("button", { name: "Tools (1/2 on)" }));
    const del = screen.getByLabelText("Enable tool delete_file");
    expect(del).not.toBeChecked();
    fireEvent.click(screen.getByLabelText("Enable tool read_file"));
    expect(c.onToolToggle).toHaveBeenCalledWith("playwright", "read_file", false);
  });
});
