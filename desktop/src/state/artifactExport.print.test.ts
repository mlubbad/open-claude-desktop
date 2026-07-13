// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";

import { printInSandbox } from "./artifactExport";

describe("printInSandbox (print-XSS hardening)", () => {
  afterEach(() => {
    document.querySelectorAll("iframe").forEach((f) => f.remove());
    vi.restoreAllMocks();
  });

  it("prints via a sandboxed, opaque-origin iframe — never a top-level window.open", () => {
    const openSpy = vi.spyOn(window, "open");
    printInSandbox("<html><body>artifact body</body></html>");

    const frame = document.querySelector("iframe");
    expect(frame).toBeTruthy();
    // allow-scripts + allow-modals (render + print) but NOT allow-same-origin — so the
    // frame can't reach the parent window, its opener, or the Tauri bridge.
    const sandbox = frame!.getAttribute("sandbox") ?? "";
    expect(sandbox).toContain("allow-scripts");
    expect(sandbox).toContain("allow-modals");
    expect(sandbox).not.toContain("allow-same-origin");
    // The document content is carried via srcdoc (not document.write into a real window).
    expect(frame!.getAttribute("srcdoc")).toContain("artifact body");
    // The old, vulnerable path (top-level window) is not used.
    expect(openSpy).not.toHaveBeenCalled();
  });
});
