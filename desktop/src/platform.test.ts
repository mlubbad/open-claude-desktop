import { describe, expect, it } from "vitest";

import { isTauri, notify, registerSummonHotkey, unregisterSummonHotkey } from "./platform";

// In the node test environment there is no Tauri global and no window — the platform
// layer must report "not Tauri" and degrade to safe no-ops without throwing.
describe("platform integration (web fallback)", () => {
  it("isTauri is false without the Tauri global", () => {
    expect(isTauri()).toBe(false);
  });

  it("registerSummonHotkey returns false in a browser/no-op env", async () => {
    let fired = false;
    const ok = await registerSummonHotkey("CmdOrControl+Shift+Space", () => {
      fired = true;
    });
    expect(ok).toBe(false);
    expect(fired).toBe(false);
  });

  it("unregister + notify never throw when unavailable", async () => {
    await expect(unregisterSummonHotkey("CmdOrControl+Shift+Space")).resolves.toBeUndefined();
    await expect(notify("title", "body")).resolves.toBeUndefined();
  });
});
