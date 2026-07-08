import { useEffect, useMemo, useRef, useState } from "react";
import Markdown from "react-markdown";
import rehypeHighlight from "rehype-highlight";
import remarkGfm from "remark-gfm";

import {
  filename,
  IFRAME_KINDS,
  isPreviewable,
  mime,
  parseCsv,
  previewMarkdown,
  printableHtml,
  typeTag,
} from "../state/artifactExport";
import { getDriveClientId, saveToDrive, setDriveClientId } from "../state/gdrive";
import { type ArtifactDoc, contentAtVersion } from "../state/transcript";
import { Icon } from "./Icon";

// Renders an artifact in a side panel, matching the reference chrome: an eye/code
// view toggle on the left of the title (with its type tag), and on the right a
// Save-to-Drive button, a Copy split-button (Download / Print as PDF), refresh,
// expand (full-screen), and close. Preview runs in a sandboxed iframe
// (sandbox="allow-scripts" WITHOUT allow-same-origin) so model-generated
// HTML/SVG/React/Mermaid cannot touch the host page, cookies, or storage.
export function ArtifactPanel({
  doc,
  onClose,
}: {
  doc: ArtifactDoc;
  onClose: () => void;
}) {
  const previewable = isPreviewable(doc.kind);
  const iframePreview = IFRAME_KINDS.has(doc.kind);
  const [tab, setTab] = useState<"preview" | "code">(previewable ? "preview" : "code");
  const [expanded, setExpanded] = useState(false);
  const [copied, setCopied] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [driveOpen, setDriveOpen] = useState(false);
  // Bumping remounts the iframe — the reference's refresh control.
  const [renderKey, setRenderKey] = useState(0);
  const menuRef = useRef<HTMLDivElement>(null);
  const driveRef = useRef<HTMLDivElement>(null);

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

  const srcDoc = useMemo(() => (iframePreview ? buildSrcDoc(shownDoc) : ""), [shownDoc, iframePreview]);
  // In-panel preview markdown for non-iframe kinds (see previewMarkdown for the rules).
  const renderMarkdown = useMemo(
    () => previewMarkdown(shownDoc.kind, shownContent, shownDoc.language),
    [shownContent, shownDoc.kind, shownDoc.language],
  );

  // Dismiss popovers on outside click / Escape (Escape swallowed from the global handler).
  useEffect(() => {
    if (!menuOpen && !driveOpen) return;
    function onDoc(e: MouseEvent) {
      if (!menuRef.current?.contains(e.target as Node)) setMenuOpen(false);
      if (!driveRef.current?.contains(e.target as Node)) setDriveOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.stopPropagation();
        e.preventDefault();
        setMenuOpen(false);
        setDriveOpen(false);
      }
    }
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey, true);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey, true);
    };
  }, [menuOpen, driveOpen]);

  function copy() {
    void navigator.clipboard?.writeText(shownContent);
    setCopied(true);
    setTimeout(() => setCopied(false), 1200);
  }

  function download() {
    const blob = new Blob([shownContent], { type: mime(doc.kind) });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename(doc);
    a.click();
    URL.revokeObjectURL(url);
  }

  function printPdf() {
    const html = printableHtml(doc.title, shownContent, previewable ? srcDoc : undefined);
    const w = window.open("", "_blank");
    if (!w) return;
    w.document.write(html);
    w.document.close();
    // Give the document (and any scripts, e.g. mermaid) a beat to render.
    setTimeout(() => w.print(), 400);
  }

  const tag = typeTag(doc.kind, doc.language);

  return (
    <section className={`artifact-panel ${expanded ? "expanded" : ""}`}>
      <header className="artifact-head">
        <div className="artifact-view-toggle" role="tablist" aria-label="View mode">
          <button
            role="tab"
            aria-selected={tab === "preview"}
            className={tab === "preview" ? "active" : ""}
            title="Preview"
            aria-label="Preview"
            disabled={!previewable}
            onClick={() => setTab("preview")}
          >
            <Icon name="eye" size={15} />
          </button>
          <button
            role="tab"
            aria-selected={tab === "code"}
            className={tab === "code" ? "active" : ""}
            title="Code"
            aria-label="Code"
            onClick={() => setTab("code")}
          >
            <Icon name="code" size={15} />
          </button>
        </div>
        <div className="artifact-title" title={doc.title}>
          <span className="artifact-title-text">{doc.title}</span>
          <span className="artifact-tag">· {tag}</span>
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
          <div className="artifact-pop-anchor" ref={driveRef}>
            <button
              className="artifact-ic"
              title="Save to Google Drive"
              aria-label="Save to Google Drive"
              aria-expanded={driveOpen}
              onClick={() => setDriveOpen((o) => !o)}
            >
              <Icon name="cloud-up" size={16} />
            </button>
            {driveOpen && (
              <DrivePopover
                name={filename(doc)}
                mimeType={mime(doc.kind)}
                content={shownContent}
                onClose={() => setDriveOpen(false)}
              />
            )}
          </div>
          <div className="artifact-split" ref={menuRef}>
            <button className="artifact-split-main" onClick={copy}>
              {copied ? "Copied" : "Copy"}
            </button>
            <button
              className="artifact-split-caret"
              title="Export options"
              aria-label="Export options"
              aria-expanded={menuOpen}
              onClick={() => setMenuOpen((o) => !o)}
            >
              <Icon name="chev-down" size={12} />
            </button>
            {menuOpen && (
              <div className="artifact-menu" role="menu" aria-label="Export">
                <button role="menuitem" onClick={() => { setMenuOpen(false); download(); }}>
                  Download as {tag}
                </button>
                <button role="menuitem" onClick={() => { setMenuOpen(false); printPdf(); }}>
                  Print as PDF
                </button>
              </div>
            )}
          </div>
          <button className="artifact-ic" title="Refresh preview" aria-label="Refresh preview"
                  onClick={() => setRenderKey((k) => k + 1)}>
            <Icon name="retry" size={15} />
          </button>
          <button className="artifact-ic" title={expanded ? "Collapse" : "Expand"}
                  aria-label={expanded ? "Collapse" : "Expand"} aria-pressed={expanded}
                  onClick={() => setExpanded((e) => !e)}>
            <Icon name="expand" size={15} />
          </button>
          <button className="artifact-ic" onClick={onClose} title="Close" aria-label="Close">
            <Icon name="x" size={15} />
          </button>
        </div>
      </header>
      <div className="artifact-body">
        {tab === "preview" && iframePreview ? (
          <iframe
            key={renderKey}
            className="artifact-preview"
            title={doc.title}
            sandbox="allow-scripts"
            srcDoc={srcDoc}
          />
        ) : tab === "preview" && shownDoc.kind === "csv" ? (
          <CsvTable text={shownContent} />
        ) : tab === "preview" && previewable ? (
          <div className="artifact-render">
            <Markdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeHighlight]}>
              {renderMarkdown}
            </Markdown>
          </div>
        ) : (
          <pre className="artifact-code">
            <code>{shownContent}</code>
          </pre>
        )}
      </div>
    </section>
  );
}

// Render a CSV artifact as a scrollable table (matching Claude Desktop's data preview).
// Caps the rendered rows so a huge export can't jank the panel; the Code tab and Download
// still give the full file.
const CSV_PREVIEW_ROWS = 500;

function CsvTable({ text }: { text: string }) {
  const { columns, rows } = useMemo(() => parseCsv(text), [text]);
  if (columns.length === 0) return <div className="artifact-render">(empty CSV)</div>;
  const shown = rows.slice(0, CSV_PREVIEW_ROWS);
  return (
    <div className="artifact-csv">
      <table>
        <thead>
          <tr>
            <th className="csv-rownum" aria-hidden="true"></th>
            {columns.map((c, i) => (
              <th key={i}>{c}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {shown.map((r, ri) => (
            <tr key={ri}>
              <td className="csv-rownum">{ri + 1}</td>
              {columns.map((_, ci) => (
                <td key={ci}>{r[ci] ?? ""}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length > CSV_PREVIEW_ROWS && (
        <div className="csv-more">
          Showing {CSV_PREVIEW_ROWS} of {rows.length} rows — open Code or Download for all.
        </div>
      )}
    </div>
  );
}

// The Save-to-Drive popover. BYOK: uploads with the USER'S OWN Google OAuth Client
// ID (stored locally); first use asks for it with pointers, later uses are one click.
function DrivePopover({
  name,
  mimeType,
  content,
  onClose,
}: {
  name: string;
  mimeType: string;
  content: string;
  onClose: () => void;
}) {
  const [clientId, setClientId] = useState(getDriveClientId());
  const [draft, setDraft] = useState(clientId);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [link, setLink] = useState<string | null>(null);

  async function upload() {
    setBusy(true);
    setErr(null);
    try {
      const res = await saveToDrive({ clientId, name, mimeType, content });
      setLink(res.link);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="drive-pop" role="dialog" aria-label="Save to Google Drive">
      <div className="drive-title">Save to Google Drive</div>
      {!clientId ? (
        <>
          <p className="drive-help">
            Bring your own Google OAuth <strong>Client ID</strong> (Web application type,
            with this app's origin authorized). It's stored only on this device and the
            upload goes straight from your browser to your Drive.
          </p>
          <input
            className="drive-input"
            placeholder="xxxxxxxx.apps.googleusercontent.com"
            aria-label="Google OAuth Client ID"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
          />
          <div className="drive-actions">
            <button className="btn-secondary" onClick={onClose}>Cancel</button>
            <button
              className="btn-primary"
              disabled={!draft.trim()}
              onClick={() => {
                setDriveClientId(draft);
                setClientId(draft.trim());
              }}
            >
              Save
            </button>
          </div>
        </>
      ) : link ? (
        <>
          <p className="drive-help">
            Saved as <strong>{name}</strong>.{" "}
            <a href={link} target="_blank" rel="noreferrer">Open in Drive</a>
          </p>
          <div className="drive-actions">
            <button className="btn-secondary" onClick={onClose}>Done</button>
          </div>
        </>
      ) : (
        <>
          <p className="drive-help">
            Upload <strong>{name}</strong> to your Drive (scope: files this app created only).
          </p>
          {err && <p className="drive-err">{err}</p>}
          <div className="drive-actions">
            <button
              className="drive-reset"
              title="Change Client ID"
              onClick={() => {
                setDriveClientId("");
                setClientId("");
              }}
            >
              Change ID
            </button>
            <button className="btn-secondary" onClick={onClose}>Cancel</button>
            <button className="btn-primary" disabled={busy} onClick={() => void upload()}>
              {busy ? "Uploading…" : "Upload"}
            </button>
          </div>
        </>
      )}
    </div>
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
