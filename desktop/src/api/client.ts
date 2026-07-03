// Typed REST + SSE client for the FastAPI backend. The single seam between the UI
// and the backend; no domain logic lives here.

import { fetchEventSource } from "@microsoft/fetch-event-source";

import type { AgentEvent } from "./events";

// In web dev, Vite proxies "/api" -> backend. In the packaged app, VITE_API_BASE
// points at the bundled backend.
const BASE = (import.meta.env?.VITE_API_BASE as string | undefined) ?? "/api";

let token: string | null = null;
export function setToken(t: string | null): void {
  token = t;
}

function authHeaders(extra?: Record<string, string>): Record<string, string> {
  const h: Record<string, string> = { ...(extra ?? {}) };
  if (token) h["Authorization"] = `Bearer ${token}`;
  return h;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: string,
  ) {
    super(`${status}: ${detail}`);
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const resp = await fetch(BASE + path, {
    method,
    headers: authHeaders(body !== undefined ? { "Content-Type": "application/json" } : undefined),
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!resp.ok) {
    let detail = resp.statusText;
    try {
      detail = (await resp.json())?.detail ?? detail;
    } catch {
      /* keep statusText */
    }
    throw new ApiError(resp.status, detail);
  }
  return (await resp.json()) as T;
}

export const api = {
  get: <T>(p: string) => request<T>("GET", p),
  post: <T>(p: string, body?: unknown) => request<T>("POST", p, body),
  put: <T>(p: string, body?: unknown) => request<T>("PUT", p, body),
  patch: <T>(p: string, body?: unknown) => request<T>("PATCH", p, body),
  del: <T>(p: string) => request<T>("DELETE", p),
};

export interface ProviderInfo {
  id: string;
  label: string;
  is_local: boolean;
  requires_key: boolean;
  has_key: boolean;
  default_model: string;
  models: string[];
  docs: string;
  is_default: boolean;
}

export interface UserProfile {
  name?: string;
  call_me?: string;
  role?: string;
  about?: string;
  preferences?: string;
}

export interface AppSettings {
  model?: string;
  provider?: string;
  effort?: string;
  theme?: string;
  profile?: UserProfile;
}

export const settings = {
  get: () => api.get<AppSettings>("/settings"),
  save: (patch: Partial<AppSettings>) => api.put<AppSettings>("/settings", patch),
};

export const providers = {
  list: () => api.get<ProviderInfo[]>("/providers"),
  setKey: (id: string, key: string) => api.put<{ id: string; has_key: boolean }>(`/providers/${id}/key`, { key }),
  deleteKey: (id: string) => api.del<{ id: string; has_key: boolean }>(`/providers/${id}/key`),
};

export interface AgentTurnRequest {
  project_id?: string | null;
  goal: string;
  history: { role: string; content: string; kind?: string }[];
  model: string;
  provider?: string | null;
  effort?: string;
  permission_mode?: string | null;
  options?: Record<string, boolean>;
  enabled_plugins?: string[];
  enabled_connectors?: string[];
  enabled_mcp?: string[];
}

// The backend routes non-project chats under this implicit project.
export const GENERAL_PROJECT = "general";

export interface Project {
  id: string;
  name: string;
  created_at?: string;
}

export interface Capacity {
  used_mb: number;
  max_mb: number;
  percent: number;
}

export interface ProjectFile {
  name: string;
  badge: string;
  size: number;
  meta?: string;
}

export const projects = {
  list: () => api.get<Project[]>("/projects"),
  create: (name: string) => api.post<Project>("/projects", { name }),
  del: (pid: string) => api.del<{ ok: boolean }>(`/projects/${pid}`),
  getInstructions: (pid: string) => api.get<{ content: string }>(`/projects/${pid}/instructions`),
  saveInstructions: (pid: string, content: string) =>
    api.put<{ ok: boolean }>(`/projects/${pid}/instructions`, { content }),
  capacity: (pid: string) => api.get<Capacity>(`/projects/${pid}/capacity`),
  files: (pid: string) => api.get<ProjectFile[]>(`/projects/${pid}/files`),
  uploadFile: async (pid: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    const resp = await fetch(`${BASE}/projects/${pid}/files`, {
      method: "POST",
      headers: authHeaders(), // no Content-Type: the browser sets the multipart boundary
      body: form,
    });
    if (!resp.ok) throw new ApiError(resp.status, await resp.text());
    return (await resp.json()) as { ok: boolean; name: string; chunks: number };
  },
};

export interface ConversationSummary {
  id: string;
  title: string;
  updated_at: string;
  updated_rel?: string;
  pinned: boolean;
  project_id?: string;
  project_name?: string;
}

export interface StoredMsg {
  role: string;
  content: string;
  kind: string;
}

export interface ConversationDetail extends ConversationSummary {
  messages: StoredMsg[];
}

export const conversations = {
  listAll: (limit = 200) => api.get<ConversationSummary[]>(`/conversations?limit=${limit}`),
  create: (pid: string, firstMessage: string) =>
    api.post<ConversationDetail>(`/projects/${pid}/conversations`, { first_message: firstMessage }),
  get: (pid: string, cid: string) => api.get<ConversationDetail>(`/projects/${pid}/conversations/${cid}`),
  save: (pid: string, cid: string, messages: StoredMsg[], title?: string) =>
    api.put<ConversationDetail>(`/projects/${pid}/conversations/${cid}`, { messages, title }),
  rename: (pid: string, cid: string, title: string) =>
    api.patch<{ ok: boolean }>(`/projects/${pid}/conversations/${cid}`, { title }),
  setPinned: (pid: string, cid: string, pinned: boolean) =>
    api.patch<{ ok: boolean }>(`/projects/${pid}/conversations/${cid}`, { pinned }),
  del: (pid: string, cid: string) => api.del<{ ok: boolean }>(`/projects/${pid}/conversations/${cid}`),
};

export interface McpServer {
  id: string;
  name: string;
  transport: string;
  command: string;
  args: string[];
  url: string;
  auth: boolean;
  status: string;
  detail: string;
  tool_count: number;
}

export interface AddMcpBody {
  name: string;
  command?: string;
  args?: string[];
  url?: string;
  transport?: string;
  env?: Record<string, string>;
  headers?: Record<string, string>;
  auth_token?: string;
}

export const mcp = {
  list: () => api.get<McpServer[]>("/mcp-servers"),
  add: (body: AddMcpBody) => api.post<McpServer>("/mcp-servers", body),
  addDemo: () => api.post<McpServer>("/mcp-servers/demo"),
  remove: (sid: string) => api.del<{ ok: boolean }>(`/mcp-servers/${sid}`),
};

// Stream an agent turn. Invokes onEvent for each typed event; resolves on `done`.
// The returned AbortController lets the caller stop the turn.
export function streamTurn(
  req: AgentTurnRequest,
  onEvent: (ev: AgentEvent) => void,
  onError?: (err: unknown) => void,
): AbortController {
  const ctrl = new AbortController();
  fetchEventSource(BASE + "/agent/turn", {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(req),
    signal: ctrl.signal,
    openWhenHidden: true,
    onmessage(msg) {
      if (!msg.data) return;
      let ev: AgentEvent;
      try {
        ev = JSON.parse(msg.data) as AgentEvent;
      } catch {
        return;
      }
      onEvent(ev);
      if (ev.type === "done") ctrl.abort();
    },
    onerror(err) {
      onError?.(err);
      throw err; // stop the built-in retry loop
    },
  }).catch((err) => {
    if (!ctrl.signal.aborted) onError?.(err);
  });
  return ctrl;
}

// Resolve a HITL approval prompt for a running turn.
export function replyPermission(
  turnId: string,
  toolCallId: string,
  decision: "approve" | "decline",
): Promise<{ resolved: boolean; decision: string }> {
  return api.post(`/agent/turn/${turnId}/permission`, { tool_call_id: toolCallId, decision });
}
