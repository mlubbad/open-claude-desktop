import { useMemo, useState } from "react";

import type { ArtifactDoc } from "../state/transcript";

// Renders an artifact in a side panel with a Preview/Code toggle. Preview runs in a
// sandboxed iframe (sandbox="allow-scripts" WITHOUT allow-same-origin) so model-
// generated HTML/SVG/React/Mermaid cannot touch the host page, cookies, or storage.
export function ArtifactPanel({
  doc,
  onClose,
}: {
  doc: ArtifactDoc;
  onClose: () => void;
}) {
  const previewable = doc.kind === "html" || doc.kind === "svg" || doc.kind === "mermaid" || doc.kind === "react";
  const [tab, setTab] = useState<"preview" | "code">(previewable ? "preview" : "code");

  const srcDoc = useMemo(() => (previewable ? buildSrcDoc(doc) : ""), [doc, previewable]);

  function copy() {
    void navigator.clipboard?.writeText(doc.content);
  }
  function download() {
    const blob = new Blob([doc.content], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${slug(doc.title)}.${ext(doc)}`;
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <section className="artifact-panel">
      <header className="artifact-head">
        <div className="artifact-title" title={doc.title}>
          {doc.title}
          {doc.version > 1 && <span className="artifact-ver">v{doc.version}</span>}
          {doc.streaming && <span className="artifact-streaming">•••</span>}
        </div>
        <div className="artifact-actions">
          {previewable && (
            <div className="artifact-tabs">
              <button className={tab === "preview" ? "active" : ""} onClick={() => setTab("preview")}>
                Preview
              </button>
              <button className={tab === "code" ? "active" : ""} onClick={() => setTab("code")}>
                Code
              </button>
            </div>
          )}
          <button onClick={copy} title="Copy">
            Copy
          </button>
          <button onClick={download} title="Download">
            ↓
          </button>
          <button onClick={onClose} title="Close">
            ✕
          </button>
        </div>
      </header>
      <div className="artifact-body">
        {tab === "preview" && previewable ? (
          <iframe
            className="artifact-preview"
            title={doc.title}
            sandbox="allow-scripts"
            srcDoc={srcDoc}
          />
        ) : (
          <pre className="artifact-code">
            <code>{doc.content}</code>
          </pre>
        )}
      </div>
    </section>
  );
}

function buildSrcDoc(doc: ArtifactDoc): string {
  const csp =
    '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; ' +
    "script-src 'unsafe-inline' https://cdn.jsdelivr.net; style-src 'unsafe-inline'; " +
    "img-src data: https:; font-src data: https:\">";
  if (doc.kind === "html") {
    // If the model already returned a full document, trust its own structure but keep
    // it inside the sandboxed iframe.
    return doc.content;
  }
  if (doc.kind === "svg") {
    return `<!doctype html><html><head>${csp}<style>body{margin:0;display:grid;place-items:center;height:100vh}</style></head><body>${doc.content}</body></html>`;
  }
  if (doc.kind === "mermaid") {
    return `<!doctype html><html><head>${csp}</head><body><pre class="mermaid">${escapeHtml(
      doc.content,
    )}</pre><script src="https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"></script><script>mermaid.initialize({startOnLoad:true});</script></body></html>`;
  }
  // react: mount the component with esm.sh-hosted React via an import map.
  return `<!doctype html><html><head>${csp}<script type="importmap">{"imports":{"react":"https://esm.sh/react@18","react-dom/client":"https://esm.sh/react-dom@18/client"}}</script></head><body><div id="root"></div><script type="module">${doc.content}\n;import React from 'react';import {createRoot} from 'react-dom/client';const C=(typeof App!=='undefined')?App:(typeof Component!=='undefined'?Component:null);if(C){createRoot(document.getElementById('root')).render(React.createElement(C));}</script></body></html>`;
}

function escapeHtml(s: string): string {
  return s.replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" })[c] ?? c);
}

function slug(s: string): string {
  return s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "artifact";
}

function ext(doc: ArtifactDoc): string {
  const map: Record<string, string> = {
    html: "html",
    svg: "svg",
    mermaid: "mmd",
    react: "jsx",
    markdown: "md",
    code: doc.language || "txt",
  };
  return map[doc.kind] ?? "txt";
}
