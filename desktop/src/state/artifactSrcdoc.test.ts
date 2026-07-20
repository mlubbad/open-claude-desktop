import { describe, expect, it } from "vitest";

import {
  buildSrcDoc,
  jsonForScriptTag,
  MERMAID_VERSION,
  normalizeMermaid,
  REACT_IMPORTS,
  rewriteExports,
  stripFence,
} from "./artifactSrcdoc";

// The exact chart from the reported "Syntax error in text — mermaid version 11.16.0"
// incident: Arabic labels + parentheses + `-->`, wrapped in a fence by the model.
const ARABIC_XYCHART = `xychart-beta
    title "Top Series by Hours Watched (2026-07-19)"
    x-axis ["الدحيح (Mobile)", "أبو الصادق (Mobile)", "الدحيح (Web)", "أبو الصادق (Web)", "شاهد على العصر (Mobile)", "الدحيح (TV)", "أبو الصادق (TV)", "المستعمرون العرب (Web)", "بودكاست بالتفصيل (Web)", "شاهد على العصر (Web)"]
    y-axis "Hours Watched" 0 --> 1000
    bar [978.8, 736.5, 525.2, 244.6, 87.0, 33.8, 23.5, 18.3, 17.2, 12.0]`;

const FENCED = "```mermaid\n" + ARABIC_XYCHART + "\n```";

// Pull the JSON-embedded source back out of a srcdoc to assert what the runtime sees.
function embeddedSource(srcdoc: string): string {
  const m = /<script id="artifact-src" type="application\/json">([\s\S]*?)<\/script>/.exec(
    srcdoc,
  );
  if (!m) throw new Error("no embedded source in srcdoc");
  return JSON.parse(m[1]);
}

describe("stripFence", () => {
  it("unwraps a closed whole-content fence", () => {
    expect(stripFence(FENCED)).toBe(ARABIC_XYCHART);
  });

  it("drops a lone opening fence while streaming (closer not yet arrived)", () => {
    expect(stripFence("```mermaid\nxychart-beta\n    bar [1]")).toBe(
      "xychart-beta\n    bar [1]",
    );
  });

  it("leaves unfenced content unchanged", () => {
    expect(stripFence(ARABIC_XYCHART)).toBe(ARABIC_XYCHART);
  });

  it("leaves fence-plus-trailing-prose unchanged", () => {
    const s = "```python\nprint(1)\n```\nAnd here is why.";
    expect(stripFence(s)).toBe(s);
  });

  it("keeps inner fences when stripping an outer markdown fence", () => {
    const s = "```markdown\n# Doc\n\n```py\nprint(1)\n```\n\ntail\n```";
    expect(stripFence(s)).toBe("# Doc\n\n```py\nprint(1)\n```\n\ntail");
  });
});

describe("normalizeMermaid", () => {
  it("strips invisible bidi/zero-width controls but keeps Arabic letters", () => {
    const dirty =
      "\u200Fxychart-beta\n\u202Abar [1]\u202C\u200B\uFEFF\u2066x\u2069";
    expect(normalizeMermaid(dirty)).toBe("xychart-beta\nbar [1]x");
    expect(normalizeMermaid("الدحيح (Mobile)")).toBe("الدحيح (Mobile)");
  });
});

describe("jsonForScriptTag", () => {
  it("embeds </script> safely", () => {
    const out = jsonForScriptTag("a</script><b>");
    expect(out).not.toContain("</script>");
    expect(JSON.parse(out)).toBe("a</script><b>");
  });
});

describe("rewriteExports", () => {
  it("binds an anonymous default function", () => {
    const out = rewriteExports("export default function () { return null; }");
    expect(out).toContain("const __ARTIFACT_DEFAULT__ = function ()");
    expect(out).not.toContain("export default");
  });

  it("keeps a named default function declaration and binds it", () => {
    const out = rewriteExports("export default function App() { return null; }");
    expect(out).toContain("function App()");
    expect(out).toContain("const __ARTIFACT_DEFAULT__ = App;");
    expect(out).not.toContain("export default");
  });

  it("binds a default class and a default arrow", () => {
    const cls = rewriteExports("export default class Board extends React.Component {}");
    expect(cls).toContain("class Board extends React.Component {}");
    expect(cls).toContain("const __ARTIFACT_DEFAULT__ = Board;");
    const arrow = rewriteExports("const X = () => null;\nexport default () => null;");
    expect(arrow).toContain("const __ARTIFACT_DEFAULT__ = () => null;");
  });

  it("binds a default identifier and strips named exports", () => {
    const out = rewriteExports(
      "export const A = 1;\nexport function helper() {}\nconst App = () => null;\nexport default App;",
    );
    expect(out).toContain("const A = 1;");
    expect(out).toContain("function helper() {}");
    expect(out).toContain("const __ARTIFACT_DEFAULT__ = App;");
    expect(out).not.toMatch(/^export /m);
  });

  it("returns source without exports unchanged", () => {
    const s = "function App() { return null; }";
    expect(rewriteExports(s)).toBe(s);
  });
});

describe("buildSrcDoc: mermaid", () => {
  const srcdoc = buildSrcDoc({ kind: "mermaid", content: FENCED, language: "" });

  it("pins the mermaid version and uses explicit render, not <pre> autoscan", () => {
    expect(MERMAID_VERSION).toBe("11.16.0");
    expect(srcdoc).toContain(`mermaid@${MERMAID_VERSION}/dist/mermaid.min.js`);
    expect(srcdoc).toContain("mermaid.render(");
    expect(srcdoc).not.toContain('<pre class="mermaid">');
    expect(srcdoc).not.toContain("startOnLoad:true");
  });

  it("embeds the EXACT reported Arabic chart, fence stripped, via JSON", () => {
    expect(embeddedSource(srcdoc)).toBe(ARABIC_XYCHART);
  });

  it("has an error surface instead of the bare bomb screen", () => {
    expect(srcdoc).toContain("artifact-error");
    expect(srcdoc).toContain("catch");
  });

  it("declares utf-8 so byte-serialized copies keep RTL text intact", () => {
    expect(srcdoc).toContain('<meta charset="utf-8">');
  });
});

describe("buildSrcDoc: react", () => {
  const content =
    'import { useState } from "react";\nexport default function App() { return <div className="p-4">hi</div>; }';
  const srcdoc = buildSrcDoc({ kind: "react", content, language: "" });

  it("ships a pinned import map covering the prompt's library roster", () => {
    for (const name of [
      "react",
      "react/jsx-runtime",
      "react-dom/client",
      "recharts",
      "lucide-react",
      "d3",
      "lodash",
      "papaparse",
      "xlsx",
      "mathjs",
      "chart.js",
      "tone",
      "three",
    ]) {
      expect(REACT_IMPORTS[name], name).toBeTruthy();
      expect(srcdoc).toContain(`"${name}"`);
    }
    expect(REACT_IMPORTS["react"]).toContain("react@18.3.1");
    expect(REACT_IMPORTS["lucide-react"]).toContain("0.383.0");
    expect(REACT_IMPORTS["three"]).toContain("0.128.0");
  });

  it("brings a JSX/TSX transform and Tailwind runtime", () => {
    expect(srcdoc).toContain("@babel/standalone");
    expect(srcdoc).toContain("Babel.transform");
    expect(srcdoc).toContain("@tailwindcss/browser");
  });

  it("embeds the rewritten (not raw) source and mounts with a fallback chain", () => {
    const embedded = embeddedSource(srcdoc);
    expect(embedded).toContain("const __ARTIFACT_DEFAULT__ = App;");
    expect(embedded).not.toContain("export default");
    expect(srcdoc).toContain("__ARTIFACT_DEFAULT__");
    expect(srcdoc).toContain("artifact-root");
  });

  it("allows both CDNs in its CSP", () => {
    expect(srcdoc).toContain("https://cdn.jsdelivr.net");
    expect(srcdoc).toContain("https://esm.sh");
  });
});

describe("buildSrcDoc: html + svg (behavior preserved)", () => {
  it("passes html through untouched when unfenced", () => {
    const html = "<!doctype html><html><body><h1>x</h1></body></html>";
    expect(buildSrcDoc({ kind: "html", content: html, language: "" })).toBe(html);
  });

  it("unwraps a fenced html document", () => {
    const html = "<!doctype html><html><body>ok</body></html>";
    expect(buildSrcDoc({ kind: "html", content: "```html\n" + html + "\n```", language: "" })).toBe(
      html,
    );
  });

  it("centers svg inside a light document", () => {
    const svg = '<svg viewBox="0 0 10 10"></svg>';
    const out = buildSrcDoc({ kind: "svg", content: svg, language: "" });
    expect(out).toContain(svg);
    expect(out).toContain("place-items:center");
    expect(out).toContain("color-scheme");
  });
});
