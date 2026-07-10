// Parsing helpers for the Add-connector form. Windows paths ("C:\Users\Mohammed
// Lubbad\…") are the norm for stdio MCP servers, so arg splitting must be quote-aware
// and must PRESERVE backslashes — a naive split(/\s+/) breaks any path with a space.

import type { AddMcpBody } from "../api/client";

// Split a command-arguments string on whitespace, honoring double and single quotes.
// Backslashes are kept literally (Windows paths); quotes only group, they don't escape.
export function splitArgs(input: string): string[] {
  const out: string[] = [];
  let cur = "";
  let quote: '"' | "'" | null = null;
  let started = false;
  for (const ch of input) {
    if (quote) {
      if (ch === quote) quote = null;
      else cur += ch;
      continue;
    }
    if (ch === '"' || ch === "'") {
      quote = ch;
      started = true; // an empty quoted arg ("") still counts as an argument
      continue;
    }
    if (/\s/.test(ch)) {
      if (started || cur) out.push(cur);
      cur = "";
      started = false;
      continue;
    }
    cur += ch;
  }
  if (started || cur) out.push(cur);
  return out;
}

// Parse "KEY=value" lines (one per line) into an env map. Blank lines and #-comments
// are ignored; values may contain '='.
export function parseEnvLines(input: string): Record<string, string> {
  const env: Record<string, string> = {};
  for (const raw of (input || "").split(/\r?\n/)) {
    const line = raw.trim();
    if (!line || line.startsWith("#")) continue;
    const eq = line.indexOf("=");
    if (eq <= 0) continue;
    env[line.slice(0, eq).trim()] = line.slice(eq + 1).trim();
  }
  return env;
}

// Parse a Claude-Desktop-style MCP config JSON into add-connector bodies. Accepts:
//   {"mcpServers": {"Name": {"command": ..., "args": [...], "env": {...}}}}
//   {"Name": {"command": ...}}                        (a bare name -> spec map)
//   {"name": "Name", "command": ...}                  (a single server object)
// Remote entries use {"url": ..., "transport"?/"type"?: "http"|"sse", "headers"?}.
// Throws Error with a user-readable message on anything invalid.
export function parseMcpJson(text: string): AddMcpBody[] {
  let data: unknown;
  try {
    data = JSON.parse(text);
  } catch {
    throw new Error("Not valid JSON — paste the server config object.");
  }
  if (typeof data !== "object" || data === null || Array.isArray(data)) {
    throw new Error("Expected a JSON object.");
  }
  const obj = data as Record<string, unknown>;

  const toBody = (name: string, spec: Record<string, unknown>): AddMcpBody => {
    const url = typeof spec.url === "string" ? spec.url.trim() : "";
    const command = typeof spec.command === "string" ? spec.command.trim() : "";
    if (!url && !command) {
      throw new Error(`"${name}" needs a "command" (local) or "url" (remote).`);
    }
    const env: Record<string, string> = {};
    if (spec.env && typeof spec.env === "object" && !Array.isArray(spec.env)) {
      for (const [k, v] of Object.entries(spec.env as Record<string, unknown>)) {
        env[k] = String(v);
      }
    }
    if (url) {
      const transport = String(spec.transport ?? spec.type ?? "http").toLowerCase();
      const headers: Record<string, string> = {};
      if (spec.headers && typeof spec.headers === "object" && !Array.isArray(spec.headers)) {
        for (const [k, v] of Object.entries(spec.headers as Record<string, unknown>)) {
          headers[k] = String(v);
        }
      }
      return { name, url, transport: transport === "sse" ? "sse" : "http", env, headers };
    }
    const args = Array.isArray(spec.args) ? spec.args.map((a) => String(a)) : [];
    return { name, command, args, env };
  };

  // Full config file: {"mcpServers": {...}}
  const servers = obj.mcpServers;
  if (servers && typeof servers === "object" && !Array.isArray(servers)) {
    const entries = Object.entries(servers as Record<string, unknown>);
    if (entries.length === 0) throw new Error('"mcpServers" is empty.');
    return entries.map(([name, spec]) => {
      if (typeof spec !== "object" || spec === null || Array.isArray(spec)) {
        throw new Error(`"${name}" must be an object.`);
      }
      return toBody(name, spec as Record<string, unknown>);
    });
  }

  // Single server object with an explicit name field.
  if (typeof obj.name === "string" && ("command" in obj || "url" in obj)) {
    return [toBody(obj.name, obj)];
  }

  // Bare {name: spec} map.
  const entries = Object.entries(obj).filter(
    ([, v]) => typeof v === "object" && v !== null && !Array.isArray(v),
  );
  if (entries.length > 0 && entries.length === Object.keys(obj).length) {
    return entries.map(([name, spec]) => toBody(name, spec as Record<string, unknown>));
  }

  throw new Error('Unrecognized shape — paste {"mcpServers": {…}} or a single server object.');
}
