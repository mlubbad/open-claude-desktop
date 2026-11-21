import { describe, expect, it, vi } from "vitest";

import { runAction } from "./runAction";

describe("runAction", () => {
  it("returns null on success, refreshes, and toggles busy", async () => {
    const busy: boolean[] = [];
    const refresh = vi.fn().mockResolvedValue(undefined);
    const res = await runAction(() => Promise.resolve("ok"), {
      setBusy: (b) => busy.push(b),
      refresh,
    });
    expect(res).toBeNull();
    expect(refresh).toHaveBeenCalledOnce();
    expect(busy).toEqual([true, false]); // busy on then off
  });

  it("clears the error at the start", async () => {
    const setErr = vi.fn();
    await runAction(() => Promise.resolve(), { setErr });
    expect(setErr).toHaveBeenCalledWith(null);
  });

  it("returns the message on failure without throwing, and does NOT refresh", async () => {
    const refresh = vi.fn();
    const busy: boolean[] = [];
    const res = await runAction(() => Promise.reject(new Error("boom")), {
      setBusy: (b) => busy.push(b),
      refresh,
    });
    expect(res).toBe("boom");
    expect(refresh).not.toHaveBeenCalled();
    expect(busy).toEqual([true, false]); // busy still reset in finally
  });

  it("stringifies a non-Error rejection", async () => {
    const res = await runAction(() => Promise.reject("nope"));
    expect(res).toBe("nope");
  });
});
