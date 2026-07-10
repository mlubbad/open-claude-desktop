// @vitest-environment jsdom
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

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
