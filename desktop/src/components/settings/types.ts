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

export type SettingsPage =
  | "general"
  | "providers"
  | "capabilities"
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

export const SETTINGS_NAV: { group: string; items: { id: SettingsPage; label: string }[] }[] = [
  {
    group: "Settings",
    items: [
      { id: "general", label: "General" },
      { id: "providers", label: "Models & keys" },
      { id: "capabilities", label: "Capabilities" },
    ],
  },
  {
    group: "Customize",
    items: [
      { id: "skills", label: "Skills" },
      { id: "connectors", label: "Connectors" },
      { id: "plugins", label: "Plugins" },
    ],
  },
];
