// Pure builders for the artifact preview iframes (srcdoc documents). Everything the
// sandbox runs is decided here, unit-tested, and pinned: mermaid renders through an
// explicit `mermaid.render()` on a JSON-embedded source (never a DOM-text roundtrip —
// that's how `-->` became `--&gt;` and produced "Syntax error in text"), and react
// artifacts get a real runtime: Babel-standalone JSX/TSX transform + a pinned import
// map (esm.sh with `?external=react` so the whole graph shares ONE React instance).
//
// The enclosing iframe is sandbox="allow-scripts" WITHOUT allow-same-origin (see
// ArtifactPanel): previews can never touch the host page, its storage, or the Tauri
// bridge, regardless of what the model wrote.

import type { ArtifactDoc } from "./transcript";

export const MERMAID_VERSION = "11.16.0";

const JSD = "https://cdn.jsdelivr.net/npm";
const ESM = "https://esm.sh";
const BABEL_URL = `${JSD}/@babel/standalone@7.26.10/babel.min.js`;
const TAILWIND_URL = `${JSD}/@tailwindcss/browser@4.1.8/dist/index.global.js`;
const MERMAID_URL = `${JSD}/mermaid@${MERMAID_VERSION}/dist/mermaid.min.js`;

// The react-artifact library roster (kept in sync with the backend system prompt —
// artifact_tools.system_prompt_section lists exactly these import names). Entries are
// lazy: an artifact that never imports `three` never fetches it. `?external=react`
// keeps dependents' `import "react"` bare so the import map resolves every copy to the
// same URL — two React instances would break hooks.
export const REACT_IMPORTS: Record<string, string> = {
  react: `${ESM}/react@18.3.1`,
  "react/jsx-runtime": `${ESM}/react@18.3.1/jsx-runtime`,
  "react-dom": `${ESM}/react-dom@18.3.1`,
  "react-dom/client": `${ESM}/react-dom@18.3.1/client`,
  recharts: `${ESM}/recharts@2.15.4?external=react,react-dom`,
  "lucide-react": `${ESM}/lucide-react@0.383.0?external=react`,
  d3: `${ESM}/d3@7.9.0`,
  lodash: `${ESM}/lodash@4.17.21`,
  "lodash-es": `${ESM}/lodash-es@4.17.21`,
  papaparse: `${ESM}/papaparse@5.5.3`,
  xlsx: `${ESM}/xlsx@0.18.5`,
  mathjs: `${ESM}/mathjs@13.2.3`,
  "chart.js": `${ESM}/chart.js@4.4.9`,
  tone: `${ESM}/tone@15.1.22`,
  three: `${ESM}/three@0.128.0`,
};

const FENCE_CLOSED = /^```[ \t]*[\w+.-]*[ \t]*\r?\n([\s\S]*?)(?:\r?\n)?```[ \t]*$/;
const FENCE_OPEN = /^```[ \t]*[\w+.-]*[ \t]*\r?\n([\s\S]*)$/;

// Models wrap artifact content in markdown fences despite instructions. The backend
// strips them at ingestion; this mirror also covers (a) transcripts persisted before
// that fix and (b) live streaming, where the closing fence hasn't arrived yet — a lone
// opening fence is dropped so the preview doesn't flash an error until artifact_close.
export function stripFence(content: string): string {
  const t = content.trim();
  const closed = FENCE_CLOSED.exec(t);
  if (closed) return closed[1];
  const open = FENCE_OPEN.exec(t);
  if (open && !open[1].includes("```")) return open[1];
  return content;
}

// Invisible bidi/zero-width controls (RLM, LRE…PDF, isolates, ZWSP, BOM) ride along
// when RTL text is pasted or model-generated; outside quoted regions they are fatal
// xychart lexer errors ("Unrecognized text") and they render as nothing — strip them.
export function normalizeMermaid(source: string): string {
  return source.replace(/[\u200B\u200E\u200F\u202A-\u202E\u2060-\u2069\uFEFF]/g, "");
}

// JSON-embed a string inside <script type="application/json"> without letting a
// literal </script> (or <!--) in the payload terminate the tag early.
export function jsonForScriptTag(s: string): string {
  return JSON.stringify(s).replace(/</g, "\\u003c");
}

// Textually turn module exports into plain declarations so the transformed source can
// run as an inline module and the mount epilogue can find the component. Handles the
// shapes models actually emit (Claude's contract: one default-exported component);
// anything stranger surfaces in the error card instead of a blank frame.
export function rewriteExports(src: string): string {
  let out = src;
  const named =
    /^(\s*)export\s+default\s+((?:async\s+)?function\s*\*?|class)\s+([A-Za-z_$][\w$]*)/m.exec(out);
  if (named) {
    out = out.replace(named[0], `${named[1]}${named[2]} ${named[3]}`);
    out += `\nconst __ARTIFACT_DEFAULT__ = ${named[3]};`;
  } else if (/^\s*export\s+default\s+/m.test(out)) {
    out = out.replace(/^(\s*)export\s+default\s+/m, "$1const __ARTIFACT_DEFAULT__ = ");
  }
  return out.replace(/^(\s*)export\s+(?=(?:const|let|var|function|class|async)\b)/gm, "$1");
}

function cspMeta(scriptHosts: string): string {
  return (
    // Charset first: srcdoc strings don't need it, but the same document survives
    // byte-serialization intact (print path, future custom-protocol previews).
    '<meta charset="utf-8">' +
    '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; ' +
    `script-src 'unsafe-inline' ${scriptHosts}; style-src 'unsafe-inline'; ` +
    "img-src data: https:; font-src data: https:\">" +
    // The preview canvas is deliberately light regardless of app theme; tell the UA so
    // form controls/scrollbars inside the sandbox match.
    '<meta name="color-scheme" content="light">'
  );
}

// Shared shell: a light page with a centered root and a styled failure card that shows
// the message AND the source — replacing mermaid's bare "Syntax error in text" bomb.
const BASE_STYLE =
  "<style>html,body{margin:0;background:#fff;color:#1a1a1a;font-family:system-ui,sans-serif}" +
  "#artifact-root{display:grid;place-items:center;min-height:100vh;padding:12px;box-sizing:border-box}" +
  ".artifact-loading{color:#8a8a8a;font-size:13px}" +
  ".artifact-error{max-width:640px;justify-self:center;align-self:start;margin-top:32px;" +
  "border:1px solid #f0c8c8;background:#fdf6f6;border-radius:10px;padding:14px 16px}" +
  ".artifact-error h1{font-size:14px;margin:0 0 6px;color:#a13d3d}" +
  ".artifact-error p{font-size:13px;margin:0 0 10px;white-space:pre-wrap}" +
  ".artifact-error pre{font-family:ui-monospace,monospace;font-size:12px;line-height:1.5;" +
  "background:#fff;border:1px solid #eee;border-radius:6px;padding:10px;overflow:auto;max-height:45vh;margin:0}" +
  "</style>";

// Inline failure helper installed as window.__artifactFail(message). DOM-built with
// textContent only, so a malicious "error message" can't inject markup.
const FAIL_HELPER =
  "var __artifactRoot=document.getElementById('artifact-root');" +
  "window.__artifactFail=function(msg){" +
  "var c=document.createElement('div');c.className='artifact-error';" +
  "var h=document.createElement('h1');h.textContent='Preview failed';" +
  "var p=document.createElement('p');p.textContent=String(msg||'Unknown error');" +
  "var pre=document.createElement('pre');pre.textContent=window.__artifactSource||'';" +
  "c.appendChild(h);c.appendChild(p);c.appendChild(pre);" +
  "__artifactRoot.innerHTML='';__artifactRoot.appendChild(c);};" +
  "window.addEventListener('error',function(e){window.__artifactFail(e.message||'Script error');});" +
  "window.addEventListener('unhandledrejection',function(e){" +
  "window.__artifactFail((e.reason&&e.reason.message)||String(e.reason||'Unhandled rejection'));});";

function mermaidSrcDoc(content: string): string {
  const source = normalizeMermaid(stripFence(content));
  return (
    `<!doctype html><html><head>${cspMeta("https://cdn.jsdelivr.net")}${BASE_STYLE}</head><body>` +
    '<div id="artifact-root"><div class="artifact-loading">Rendering diagram…</div></div>' +
    `<script id="artifact-src" type="application/json">${jsonForScriptTag(source)}</script>` +
    `<script src="${MERMAID_URL}"></script>` +
    "<script>(function(){" +
    FAIL_HELPER +
    "var src='';try{src=JSON.parse(document.getElementById('artifact-src').textContent);}" +
    "catch(e){return window.__artifactFail('Could not read the diagram source.');}" +
    "window.__artifactSource=src;" +
    "if(!window.mermaid){return window.__artifactFail('mermaid failed to load (offline or blocked?)');}" +
    "mermaid.initialize({startOnLoad:false,securityLevel:'strict',theme:'default'});" +
    "mermaid.render('artifact-diagram',src).then(function(r){" +
    "__artifactRoot.innerHTML=r.svg;var svg=__artifactRoot.querySelector('svg');" +
    "if(svg){svg.style.maxWidth='100%';svg.style.height='auto';}" +
    "}).catch(function(e){window.__artifactFail(String((e&&e.message)||e));});" +
    "})();</script></body></html>"
  );
}

// Appended to the (rewritten) component source before the Babel transform: mounts the
// default export, falling back to conventional names, all through the import map.
const MOUNT_EPILOGUE =
  "\n;import { createRoot as __artifactCreateRoot } from \"react-dom/client\";" +
  "\nimport { createElement as __artifactCreateElement } from \"react\";" +
  "\nconst __artifactC =" +
  " (typeof __ARTIFACT_DEFAULT__ !== \"undefined\" ? __ARTIFACT_DEFAULT__ : undefined) ??" +
  " (typeof App !== \"undefined\" ? App : undefined) ??" +
  " (typeof Component !== \"undefined\" ? Component : undefined);" +
  "\nif (__artifactC) {" +
  " __artifactCreateRoot(document.getElementById(\"artifact-root\")).render(__artifactCreateElement(__artifactC));" +
  "} else {" +
  " window.__artifactFail(\"No component found: give the artifact a default-exported React component (or name it App).\");" +
  "}";

function reactSrcDoc(content: string): string {
  const source = rewriteExports(stripFence(content)) + MOUNT_EPILOGUE;
  const importMap = JSON.stringify({ imports: REACT_IMPORTS });
  return (
    `<!doctype html><html><head>${cspMeta("https://cdn.jsdelivr.net https://esm.sh")}` +
    BASE_STYLE +
    `<script type="importmap">${importMap}</script>` +
    `<script src="${TAILWIND_URL}"></script>` +
    "</head><body>" +
    '<div id="artifact-root"><div class="artifact-loading">Building component…</div></div>' +
    `<script id="artifact-src" type="application/json">${jsonForScriptTag(source)}</script>` +
    `<script src="${BABEL_URL}"></script>` +
    "<script>(function(){" +
    FAIL_HELPER +
    "var raw='';try{raw=JSON.parse(document.getElementById('artifact-src').textContent);}" +
    "catch(e){return window.__artifactFail('Could not read the component source.');}" +
    "window.__artifactSource=raw;" +
    "if(!window.Babel){return window.__artifactFail('Transform runtime failed to load (offline or blocked?)');}" +
    "var out;try{out=Babel.transform(raw,{filename:'artifact.tsx'," +
    "presets:[['react',{runtime:'automatic'}],['typescript',{isTSX:true,allExtensions:true}]]}).code;}" +
    "catch(e){return window.__artifactFail('Syntax error: '+((e&&e.message)||e));}" +
    "var s=document.createElement('script');s.type='module';s.textContent=out;" +
    "document.body.appendChild(s);" +
    "})();</script></body></html>"
  );
}

export function buildSrcDoc(doc: Pick<ArtifactDoc, "kind" | "content" | "language">): string {
  if (doc.kind === "html") {
    // A full model-authored document: trust its structure (fence-stripped only) and let
    // the sandboxed iframe be the enforcement boundary.
    return stripFence(doc.content);
  }
  if (doc.kind === "svg") {
    return (
      `<!doctype html><html><head>${cspMeta("https://cdn.jsdelivr.net")}` +
      "<style>body{margin:0;display:grid;place-items:center;height:100vh}</style></head>" +
      `<body>${stripFence(doc.content)}</body></html>`
    );
  }
  if (doc.kind === "mermaid") return mermaidSrcDoc(doc.content);
  return reactSrcDoc(doc.content);
}
