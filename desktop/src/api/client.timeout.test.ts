// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";

import { api, ApiError } from "./client";

describe("REST request timeout (F-21 reliability)", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it("aborts a hung request and rejects with a typed 408 instead of hanging forever", async () => {
    vi.useFakeTimers();
    // A fetch that never resolves on its own — it only settles when its abort signal
    // fires, i.e. when our deadline trips.
    vi.stubGlobal("fetch", (_url: string, opts: { signal: AbortSignal }) =>
      new Promise((_resolve, reject) => {
        opts.signal.addEventListener("abort", () =>
          reject(Object.assign(new Error("aborted"), { name: "AbortError" })));
      }),
    );

    const p = api.get("/anything").catch((e) => e);
    await vi.advanceTimersByTimeAsync(120_000); // reach the deadline
    const err = await p;
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(408);
  });

  it("does not abort a request that responds before the deadline", async () => {
    vi.stubGlobal("fetch", () =>
      Promise.resolve({ ok: true, json: () => Promise.resolve({ value: 42 }) } as Response),
    );
    await expect(api.get<{ value: number }>("/quick")).resolves.toEqual({ value: 42 });
  });
});
