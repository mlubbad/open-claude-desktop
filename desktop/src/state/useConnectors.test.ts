import { describe, expect, it } from "vitest";

import { reconcileEnabled, requiredFields, toggleId } from "./useConnectors";

describe("toggleId", () => {
  it("adds an id that is absent", () => {
    expect(toggleId([], "a")).toEqual(["a"]);
    expect(toggleId(["a"], "b")).toEqual(["a", "b"]);
  });

  it("removes an id that is present", () => {
    expect(toggleId(["a", "b"], "a")).toEqual(["b"]);
    expect(toggleId(["a"], "a")).toEqual([]);
  });
});

describe("requiredFields", () => {
  it("returns only required fields without a default", () => {
    const uc = {
      api_key: { required: true, title: "API Key" },
      region: { required: true, default: "us" }, // has default -> backend fills it
      note: { required: false }, // optional
    };
    expect(requiredFields(uc).map((f) => f.key)).toEqual(["api_key"]);
  });

  it("handles missing/empty user_config", () => {
    expect(requiredFields(undefined)).toEqual([]);
    expect(requiredFields({})).toEqual([]);
  });
});

describe("reconcileEnabled", () => {
  const servers = [
    { id: "slack", status: "connected" },
    { id: "bigquery", status: "error" }, // auth failed → must drop out
    { id: "gmail", status: "connected" },
  ];
  it("drops enabled ids that are erroring or gone", () => {
    // bigquery is enabled but now erroring → removed; a stale id ("old") → removed.
    expect(reconcileEnabled(["slack", "bigquery", "old"], servers)).toEqual(["slack"]);
  });
  it("keeps healthy enabled ids", () => {
    expect(reconcileEnabled(["slack", "gmail"], servers)).toEqual(["slack", "gmail"]);
  });
  it("is empty when nothing is enabled", () => {
    expect(reconcileEnabled([], servers)).toEqual([]);
  });
});
