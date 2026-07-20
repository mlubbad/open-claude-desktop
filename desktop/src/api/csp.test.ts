import { describe, expect, it } from "vitest";

// The Tauri config lives outside src/; importing it as JSON (resolveJsonModule) keeps
// this a pure type-checkable test with no node:fs dependency. It's a test-only import —
// vite never bundles it into the app.
import tauriConf from "../../src-tauri/tauri.conf.json";

// Regression guard for the packaged-desktop connectivity blocker (audit F-01): the
// bundled app resolves its API base to http://127.0.0.1:8000 (see client.ts
// `tauriApiBase`), so the Tauri CSP `connect-src` MUST allow that exact origin — a
// mismatch (e.g. allowing only `localhost`) silently blocks every REST + SSE call in
// the shipped app, which CI's unit/build steps don't otherwise exercise. If you change
// the client's loopback origin, change the CSP (and this test) together.
describe("Tauri CSP ↔ client API base agreement", () => {
  const csp: string = tauriConf.app.security.csp;
  const connectSrc = csp
    .split(";")
    .map((d) => d.trim())
    .find((d) => d.startsWith("connect-src"));

  it("has a connect-src directive", () => {
    expect(connectSrc).toBeTruthy();
  });

  it("allows the loopback HTTP + WS origin the client actually uses", () => {
    // These two must match `tauriApiBase()` in client.ts.
    expect(connectSrc).toContain("http://127.0.0.1:8000");
    expect(connectSrc).toContain("ws://127.0.0.1:8000");
  });
});

// Artifact previews render in sandboxed srcdoc iframes, and about:srcdoc documents
// INHERIT the embedding document's CSP — they can only tighten it from inside, never
// loosen it. So the packaged app's policy must admit everything the preview runtimes
// in state/artifactSrcdoc.ts use (mermaid + Babel + Tailwind from cdn.jsdelivr.net,
// the react module graph from esm.sh, inline bootstrap scripts). Trade-off documented
// in docs/superpowers/specs/2026-07-20-artifacts-claude-parity-design.md §3.5.
describe("Tauri CSP ↔ artifact preview runtime agreement", () => {
  const csp: string = tauriConf.app.security.csp;
  const directive = (name: string) =>
    csp
      .split(";")
      .map((d) => d.trim())
      .find((d) => d.startsWith(name));

  it("script-src admits the preview CDNs and inline bootstraps", () => {
    const scriptSrc = directive("script-src");
    expect(scriptSrc).toBeTruthy();
    expect(scriptSrc).toContain("'self'");
    expect(scriptSrc).toContain("'unsafe-inline'");
    expect(scriptSrc).toContain("https://cdn.jsdelivr.net");
    expect(scriptSrc).toContain("https://esm.sh");
  });

  it("font-src allows data: (mermaid/tailwind inline fonts)", () => {
    expect(directive("font-src")).toContain("data:");
  });
});
