// Shared prop contracts for the Settings modal pages. The parent (App) builds these
// from the use* hooks and passes them straight through; every callback is unchanged.

import type {
  AddMcpBody,
  MarketplacePlugin,
  MarketplaceSource,
  McpServer,
  PluginSummary,
  SkillSummary,
} from "../../api/client";
import type { IconName } from "../Icon";

export type SettingsPage =
  | "general"
  | "providers"
  | "account"
  | "privacy"
  | "billing"
  | "usage"
  | "capabilities"
  | "claude-code"
  | "cowork"
  | "chrome"
  | "desktop-general"
  | "extensions"
  | "developer"
  | "skills"
  | "connectors"
  | "plugins";

export interface SkillControls {
  list: SkillSummary[];
  busy: boolean;
  allowRemote: boolean;
  importFile: (filename: string, content: string) => Promise<string | null>;
  importZip: (file: File) => Promise<string | null>;
  importFromRepo: (url: string, ref?: string) => Promise<string | null>;
  onRemove: (name: string) => void;
}

export interface ConnectorControls {
  servers: McpServer[];
  enabled: string[];
  err: string | null;
  onAdd: (body: AddMcpBody) => void;
  onInstall: (file: File) => void;
  onAddOAuth: (name: string, url: string) => void;
  onAuthorize: (sid: string) => void;
  onRemove: (sid: string) => void;
  onToggle: (sid: string) => void;
  onRetry: (sid: string) => void;
  retrying: string | null; // server id currently re-connecting (Retry pressed)
}

export interface PluginControls {
  installed: PluginSummary[];
  market: MarketplacePlugin[];
  sources: MarketplaceSource[];
  allowRemote: boolean;
  enabled: string[];
  err: string | null;
  busy: string | null;
  onToggle: (name: string) => void;
  onInstall: (name: string) => void;
  onUninstall: (name: string) => void;
  onAddSource: (url: string, ref?: string, name?: string) => Promise<string | null>;
  onRemoveSource: (id: string) => void;
}

// Grouped left-nav, mirroring Claude Desktop's Settings window. `keywords` feed the
// nav search box (matches label + keywords, case-insensitive). `icon` names come
// from the shared Icon set.
export interface SettingsNavItem {
  id: SettingsPage;
  label: string;
  icon: IconName;
  keywords?: string;
}

export const SETTINGS_NAV: { group: string; items: SettingsNavItem[] }[] = [
  {
    group: "Settings",
    items: [
      { id: "general", label: "General", icon: "sliders", keywords: "profile name instructions appearance theme font motion voice" },
      { id: "providers", label: "Models & keys", icon: "sliders", keywords: "byok api key provider model openai anthropic ollama" },
      { id: "account", label: "Account", icon: "eye", keywords: "devices sessions log out organization" },
      { id: "privacy", label: "Privacy", icon: "eye", keywords: "data export shared memory location training" },
      { id: "billing", label: "Billing", icon: "chart", keywords: "plan payment invoices subscription" },
      { id: "usage", label: "Usage", icon: "chart", keywords: "limits credits session weekly" },
      { id: "capabilities", label: "Capabilities", icon: "bulb", keywords: "memory artifacts code execution search network tools autonomy approvals" },
      { id: "claude-code", label: "Claude Code", icon: "code", keywords: "sessions worktree pull requests browser tokens" },
      { id: "cowork", label: "Cowork", icon: "note", keywords: "dispatch files trusted folders instructions" },
      { id: "chrome", label: "Claude in Chrome", icon: "share", keywords: "browser extension sites permissions" },
    ],
  },
  {
    group: "Desktop app",
    items: [
      { id: "desktop-general", label: "General", icon: "panel", keywords: "shortcut tray awake computer use" },
      { id: "extensions", label: "Extensions", icon: "plus", keywords: "mcpb dxt install local tools" },
      { id: "developer", label: "Developer", icon: "code", keywords: "mcp servers config logs" },
    ],
  },
  {
    group: "Customize",
    items: [
      { id: "skills", label: "Skills", icon: "bulb", keywords: "import zip repository markdown" },
      { id: "connectors", label: "Connectors", icon: "share", keywords: "mcp remote oauth stdio add" },
      { id: "plugins", label: "Plugins", icon: "archive", keywords: "marketplace install tools" },
    ],
  },
];
