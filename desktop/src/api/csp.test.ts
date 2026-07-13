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
