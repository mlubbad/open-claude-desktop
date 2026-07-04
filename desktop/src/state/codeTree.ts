// Pure flat→nested conversion for the Code tab's file explorer. The backend returns a
// flat, sorted list of {path, type}; this folds it into a tree the UI can render, with
// directories before files at each level and both groups sorted by name.

import type { CodeEntry } from "../api/client";

export interface TreeNode {
  name: string;
  path: string;
  type: "file" | "dir";
  children: TreeNode[];
}

function newDir(name: string, path: string): TreeNode {
  return { name, path, type: "dir", children: [] };
}

// Build a nested tree from flat entries. Intermediate directories are synthesized even
// if the backend didn't list them explicitly, so a file's parents always exist.
export function buildTree(entries: CodeEntry[]): TreeNode[] {
  const root: TreeNode = newDir("", "");
  const dirs = new Map<string, TreeNode>([["", root]]);

  const ensureDir = (path: string): TreeNode => {
    const existing = dirs.get(path);
    if (existing) return existing;
    const slash = path.lastIndexOf("/");
    const parent = ensureDir(slash === -1 ? "" : path.slice(0, slash));
    const node = newDir(slash === -1 ? path : path.slice(slash + 1), path);
    parent.children.push(node);
    dirs.set(path, node);
    return node;
  };

  for (const e of entries) {
    const slash = e.path.lastIndexOf("/");
    const parentPath = slash === -1 ? "" : e.path.slice(0, slash);
    const name = slash === -1 ? e.path : e.path.slice(slash + 1);
    if (e.type === "dir") {
      ensureDir(e.path);
    } else {
      ensureDir(parentPath).children.push({ name, path: e.path, type: "file", children: [] });
    }
  }
  sortTree(root);
  return root.children;
}

// Dirs first, then files; each group alphabetical (case-insensitive).
export function sortTree(node: TreeNode): void {
  node.children.sort((a, b) => {
    if (a.type !== b.type) return a.type === "dir" ? -1 : 1;
    return a.name.toLowerCase().localeCompare(b.name.toLowerCase());
  });
  for (const c of node.children) if (c.type === "dir") sortTree(c);
}

// A code-fence language hint from a filename extension (cosmetic).
export function langOf(path: string): string {
  const ext = (path.split(".").pop() ?? "").toLowerCase();
  const map: Record<string, string> = {
    ts: "typescript", tsx: "tsx", js: "javascript", jsx: "jsx", py: "python",
    json: "json", md: "markdown", css: "css", html: "html", sh: "bash",
    yaml: "yaml", yml: "yaml", sql: "sql", rs: "rust", go: "go", toml: "toml",
  };
  return map[ext] ?? "";
}
