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
  printInSandbox,
  typeTag,
} from "../state/artifactExport";
import { buildSrcDoc, stripFence } from "../state/artifactSrcdoc";
import { projects as projectApi } from "../api/client";
import { getDriveClientId, saveToDrive, setDriveClientId } from "../state/gdrive";
import { type ArtifactDoc, contentAtVersion } from "../state/transcript";
import { useMenuFit } from "../state/useMenuFit";
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
  projectId = null,
  projectName = null,
  onAdded,
}: {
  doc: ArtifactDoc;
  onClose: () => void;
  // The conversation's active project (null = General/no project). When set, the
  // export menu offers "Add to project" to file this artifact into its knowledge base.
  projectId?: string | null;
  projectName?: string | null;
  onAdded?: () => void;
}) {
  const previewable = isPreviewable(doc.kind);
  const iframePreview = IFRAME_KINDS.has(doc.kind);
  const [tab, setTab] = useState<"preview" | "code">(previewable ? "preview" : "code");
  const [expanded, setExpanded] = useState(false);
  const [copied, setCopied] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [driveOpen, setDriveOpen] = useState(false);
  const [addState, setAddState] = useState<"idle" | "adding" | "added" | "error">("idle");
  // Bumping remounts the iframe — the reference's refresh control.
  const [renderKey, setRenderKey] = useState(0);
  const menuRef = useRef<HTMLDivElement>(null);
  const driveRef = useRef<HTMLDivElement>(null);
  const exportMenuRef = useRef<HTMLDivElement>(null);
  useMenuFit(exportMenuRef, menuOpen);

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
  // Preview paths render fence-stripped content (old transcripts persisted fenced
  // bodies); Copy/Download keep the stored source verbatim.
  const cleanContent = useMemo(() => stripFence(shownContent), [shownContent]);
  // In-panel preview markdown for non-iframe kinds (see previewMarkdown for the rules).
  const renderMarkdown = useMemo(
    () => previewMarkdown(shownDoc.kind, cleanContent, shownDoc.language),
    [cleanContent, shownDoc.kind, shownDoc.language],
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

  // File the current version into the active project's knowledge base, so the agent
  // can cite it in later turns of the same conversation (Claude-Desktop parity). Uses
  // the same name/mime the Download action would, so the stored file is well-formed.
  async function addToProject() {
    if (!projectId || addState === "adding") return;
    setAddState("adding");
    try {
      const file = new File([shownContent], filename(doc), { type: mime(doc.kind) });
      await projectApi.uploadFile(projectId, file);
      setAddState("added");
      onAdded?.();
      setTimeout(() => {
        setMenuOpen(false);
        setAddState("idle");
      }, 1200);
    } catch {
      setAddState("error");
      setTimeout(() => setAddState("idle"), 2400);
    }
  }

  function printPdf() {
    // Sandboxed-iframe print (see printInSandbox): no privileged top-level window, so a
    // model-authored HTML artifact can't reach the opener or Tauri bridge off a Print.
    printInSandbox(printableHtml(doc.title, shownContent, previewable ? srcDoc : undefined));
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
              <div className="artifact-menu" role="menu" aria-label="Export" ref={exportMenuRef}>
                <button role="menuitem" onClick={() => { setMenuOpen(false); download(); }}>
                  Download as {tag}
                </button>
                <button role="menuitem" onClick={() => { setMenuOpen(false); printPdf(); }}>
                  Print as PDF
                </button>
                {projectId && (
                  <>
                    <div className="artifact-menu-sep" role="separator" />
                    <button
                      role="menuitem"
                      className={addState === "added" ? "is-added" : ""}
                      disabled={addState === "adding"}
                      onClick={() => void addToProject()}
                    >
                      {addState === "adding"
                        ? "Adding…"
                        : addState === "added"
                          ? "Added ✓"
                          : addState === "error"
                            ? "Couldn't add — retry"
                            : `Add to ${projectName || "project"}`}
                    </button>
                  </>
                )}
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
          <CsvTable text={cleanContent} />
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
  const popRef = useRef<HTMLDivElement>(null);
  useMenuFit(popRef, true); // only mounted while open

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
    <div className="drive-pop" role="dialog" aria-label="Save to Google Drive" ref={popRef}>
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

