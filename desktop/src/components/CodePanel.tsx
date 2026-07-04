import { useState } from "react";

import type { CodeFile } from "../api/client";
import type { TreeNode } from "../state/codeTree";

// The Code tab's left region: a collapsible file tree over the project workspace (the
// same sandbox the agent's text_editor/bash tools edit) plus a read-only file viewer.
export function CodePanel({
  tree,
  selected,
  file,
  err,
  onOpen,
  onRefresh,
}: {
  tree: TreeNode[];
  selected: string | null;
  file: CodeFile | null;
  err: string | null;
  onOpen: (path: string) => void;
  onRefresh: () => void;
}) {
  return (
    <div className="code-panel">
      <div className="code-tree">
        <div className="code-tree-head">
          <span>Workspace</span>
          <button className="icon-btn" title="Refresh" onClick={onRefresh}>
            ⟳
          </button>
        </div>
        {err && <div className="settings-err">{err}</div>}
        <div className="code-tree-body">
          {tree.length === 0 && <div className="code-empty">No files yet. Ask the agent to create some.</div>}
          {tree.map((n) => (
            <TreeItem key={n.path} node={n} depth={0} selected={selected} onOpen={onOpen} />
          ))}
        </div>
      </div>
      <div className="code-view">
        {file ? (
          <>
            <div className="code-view-head">
              <span className="code-view-path">{file.path ?? selected}</span>
              {file.truncated && <span className="code-view-note">truncated</span>}
            </div>
            {file.error ? (
              <div className="settings-err">{file.error}</div>
            ) : file.binary ? (
              <div className="code-empty">Binary file ({file.size ?? 0} bytes) — not shown.</div>
            ) : (
              <pre className="code-view-body">
                <code>{file.content}</code>
              </pre>
            )}
          </>
        ) : (
          <div className="code-empty">Select a file to view it.</div>
        )}
      </div>
    </div>
  );
}

function TreeItem({
  node,
  depth,
  selected,
  onOpen,
}: {
  node: TreeNode;
  depth: number;
  selected: string | null;
  onOpen: (path: string) => void;
}) {
  const [open, setOpen] = useState(depth < 1); // top level expanded by default
  const pad = { paddingLeft: 8 + depth * 12 };

  if (node.type === "dir") {
    return (
      <>
        <div className="code-node code-dir" style={pad} onClick={() => setOpen((o) => !o)}>
          <span className="code-chev">{open ? "▾" : "▸"}</span> {node.name}
        </div>
        {open && node.children.map((c) => (
          <TreeItem key={c.path} node={c} depth={depth + 1} selected={selected} onOpen={onOpen} />
        ))}
      </>
    );
  }
  return (
    <div
      className={`code-node code-file ${selected === node.path ? "active" : ""}`}
      style={pad}
      onClick={() => onOpen(node.path)}
    >
      {node.name}
    </div>
  );
}
