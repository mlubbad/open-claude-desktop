import { describe, expect, it } from "vitest";

import { parseEnvLines, parseMcpJson, splitArgs } from "./mcpConfig";

describe("splitArgs", () => {
  it("splits on whitespace", () => {
    expect(splitArgs("run windows-mcp")).toEqual(["run", "windows-mcp"]);
  });

  it("keeps a quoted Windows path with spaces as ONE argument, backslashes intact", () => {
    // The exact failure from the report: a username with a space.
    const input =
      '--directory "C:\\Users\\Developer\\AppData\\Roaming\\Claude\\Claude Extensions\\ant.dir.cursortouch.windows-mcp" run windows-mcp';
    expect(splitArgs(input)).toEqual([
      "--directory",
      "C:\\Users\\Developer\\AppData\\Roaming\\Claude\\Claude Extensions\\ant.dir.cursortouch.windows-mcp",
      "run",
      "windows-mcp",
    ]);
  });

  it("supports single quotes and empty quoted args", () => {
    expect(splitArgs("-m 'hello world' \"\"")).toEqual(["-m", "hello world", ""]);
  });

  it("handles empty input", () => {
    expect(splitArgs("")).toEqual([]);
    expect(splitArgs("   ")).toEqual([]);
  });
});

describe("parseEnvLines", () => {
  it("parses KEY=value lines, ignoring blanks and comments", () => {
    expect(parseEnvLines("MODE=local\n\n# note\nAPI_KEY=abc=def\n")).toEqual({
      MODE: "local",
      API_KEY: "abc=def", // value may contain '='
    });
  });

  it("ignores malformed lines", () => {
    expect(parseEnvLines("=nokey\njusttext")).toEqual({});
  });
});

describe("parseMcpJson", () => {
  it("parses a full Claude-Desktop-style mcpServers config", () => {
    const text = JSON.stringify({
      mcpServers: {
        "Windows-MCP": {
          command: "uv",
          args: ["--directory", "C:\\Users\\Developer\\AppData\\x", "run", "windows-mcp"],
          env: { MODE: "local", WINDOWS_MCP_DEBUG: "false" },
        },
      },
    });
    expect(parseMcpJson(text)).toEqual([
      {
        name: "Windows-MCP",
        command: "uv",
        args: ["--directory", "C:\\Users\\Developer\\AppData\\x", "run", "windows-mcp"],
        env: { MODE: "local", WINDOWS_MCP_DEBUG: "false" },
      },
    ]);
  });

  it("parses a bare name->spec map and a single named object", () => {
    expect(parseMcpJson('{"svc": {"command": "npx", "args": ["-y", "x"]}}')).toEqual([
      { name: "svc", command: "npx", args: ["-y", "x"], env: {} },
    ]);
    expect(parseMcpJson('{"name": "svc", "url": "https://x/mcp", "type": "sse"}')).toEqual([
      { name: "svc", url: "https://x/mcp", transport: "sse", env: {}, headers: {} },
    ]);
  });

  it("rejects invalid input with readable errors", () => {
    expect(() => parseMcpJson("not json")).toThrow(/valid JSON/);
    expect(() => parseMcpJson('{"mcpServers": {}}')).toThrow(/empty/);
    expect(() => parseMcpJson('{"mcpServers": {"x": {}}}')).toThrow(/command.*url/);
    expect(() => parseMcpJson('{"a": 1}')).toThrow(/Unrecognized/);
  });
});
