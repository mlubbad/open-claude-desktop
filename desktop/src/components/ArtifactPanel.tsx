import { useEffect, useMemo, useState } from "react";

import { type ArtifactDoc, contentAtVersion } from "../state/transcript";

// Renders an artifact in a side panel with a Preview/Code toggle and version
// navigation. Preview runs in a sandboxed iframe (sandbox="allow-scripts" WITHOUT
// allow-same-origin) so model-generated HTML/SVG/React/Mermaid cannot touch the host
// page, cookies, or storage.
export function ArtifactPanel({
  doc,
  onClose,
}: {
  doc: ArtifactDoc;
  onClose: () => void;
}) {
  const previewable = doc.kind === "html" || doc.kind === "svg" || doc.kind === "mermaid" || doc.kind === "react";
  const [tab, setTab] = useState<"preview" | "code">(previewable ? "preview" : "code");

  // Which version is on screen. Snap to the newest whenever a new version lands so a
  // fresh revision is shown live; the user can then page back through the history.
  const total = Math.max(doc.version, doc.versions?.length ?? 0);
  const [view, setView] = useState(total);
  useEffect(() => setView(doc.version), [doc.version]);
  const shownVersion = Math.min(Math.max(view, 1), Math.max(total, 1));
  const isLatest = shownVersion >= total;
  const shownContent = contentAtVersion(doc, shownVersion);
  // Render the currently-selected version (not always the live content).
  const shownDoc = isLatest ? doc : { ...doc, content: shownContent };

  const srcDoc = useMemo(() => (previewable ? buildSrcDoc(shownDoc) : ""), [shownDoc, previewable]);

  function copy() {
    void navigator.clipboard?.writeText(shownContent);
  }
  function download() {
    const blob = new Blob([shownContent], { type: "text/plain" });
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
          {total > 1 && (
            <span className="artifact-vernav">
              <button
                className="artifact-vbtn"
                disabled={shownVersion <= 1}
                title="Previous version"
                onClick={() => setView(shownVersion - 1)}
              >
                ‹
              </button>
              <span className="artifact-ver">
                v{shownVersion}/{total}
              </span>
              <button
                className="artifact-vbtn"
                disabled={shownVersion >= total}
                title="Next version"
                onClick={() => setView(shownVersion + 1)}
              >
                ›
              </button>
            </span>
          )}
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
            <code>{shownContent}</code>
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
    "img-src data: https:; font-src data: https:\">" +
    // The preview canvas is deliberately light regardless of app theme; tell the UA so
    // form controls/scrollbars inside the sandbox match.
    '<meta name="color-scheme" content="light">';
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
