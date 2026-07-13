// @vitest-environment jsdom
import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const branchesSpy = vi.fn(async (_pid: string, _cid: string) => ({
  root: "root",
  current: "c1",
  nodes: [
    { id: "root", title: "t", parent_id: null, fork_index: null, updated_at: "", project_id: "p1" },
    { id: "c1", title: "t", parent_id: "root", fork_index: 0, updated_at: "", project_id: "p1" },
  ],
}));

vi.mock("../api/client", () => ({
  conversations: { branches: (pid: string, cid: string) => branchesSpy(pid, cid) },
}));

import { useBranchFamily } from "./useBranchFamily";

describe("useBranchFamily", () => {
  beforeEach(() => branchesSpy.mockClear());

  it("fetches the family for the open conversation", async () => {
    const { result } = renderHook(() => useBranchFamily({ cid: "c1", pid: "p1" }, true));
    await waitFor(() => expect(result.current?.nodes).toHaveLength(2));
    expect(branchesSpy).toHaveBeenCalledWith("p1", "c1");
  });

  it("does not fetch for an incognito (disabled) conversation", async () => {
    const { result } = renderHook(() => useBranchFamily({ cid: "c1", pid: "p1" }, false));
    expect(result.current).toBeNull();
    expect(branchesSpy).not.toHaveBeenCalled();
  });

  it("returns null with no open conversation", async () => {
    const { result } = renderHook(() => useBranchFamily(null, true));
    expect(result.current).toBeNull();
    expect(branchesSpy).not.toHaveBeenCalled();
  });

  it("degrades to null when the fetch fails", async () => {
    branchesSpy.mockRejectedValueOnce(new Error("offline"));
    const { result } = renderHook(() => useBranchFamily({ cid: "c1", pid: "p1" }, true));
    await waitFor(() => expect(branchesSpy).toHaveBeenCalled());
    expect(result.current).toBeNull();
  });
});
