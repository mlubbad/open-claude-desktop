import { describe, expect, it } from "vitest";

import type { CodeEntry } from "../api/client";
import { buildTree, langOf } from "./codeTree";

const entries: CodeEntry[] = [
  { path: "README.md", type: "file", size: 10 },
  { path: "src", type: "dir", size: 0 },
  { path: "src/main.py", type: "file", size: 20 },
  { path: "src/util.py", type: "file", size: 5 },
  { path: "src/lib", type: "dir", size: 0 },
  { path: "src/lib/a.py", type: "file", size: 3 },
];

describe("buildTree", () => {
  it("nests files under their directories", () => {
    const tree = buildTree(entries);
    const src = tree.find((n) => n.name === "src")!;
    expect(src.type).toBe("dir");
    const names = src.children.map((c) => c.name);
    expect(names).toContain("main.py");
    expect(names).toContain("lib");
    const lib = src.children.find((c) => c.name === "lib")!;
    expect(lib.children.map((c) => c.name)).toEqual(["a.py"]);
  });

  it("orders dirs before files, each alphabetical", () => {
    const tree = buildTree(entries);
    // top level: src (dir) before README.md (file)
    expect(tree.map((n) => n.name)).toEqual(["src", "README.md"]);
    const src = tree.find((n) => n.name === "src")!;
    // lib (dir) before main.py, util.py (files, alphabetical)
    expect(src.children.map((c) => c.name)).toEqual(["lib", "main.py", "util.py"]);
  });

  it("synthesizes intermediate dirs not listed explicitly", () => {
    const tree = buildTree([{ path: "a/b/c.txt", type: "file", size: 1 }]);
    const a = tree.find((n) => n.name === "a")!;
    const b = a.children.find((n) => n.name === "b")!;
    expect(b.children[0].name).toBe("c.txt");
    expect(b.children[0].path).toBe("a/b/c.txt");
  });

  it("handles an empty tree", () => {
    expect(buildTree([])).toEqual([]);
  });
});

describe("langOf", () => {
  it("maps extensions to fence languages", () => {
    expect(langOf("main.py")).toBe("python");
    expect(langOf("app.tsx")).toBe("tsx");
    expect(langOf("x.unknown")).toBe("");
  });
});
