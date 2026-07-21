// Minimal Node builtin typings for the few tests that run under plain Node (vitest).
// The app tsconfig deliberately ships NO @types/node — webview code must not lean on
// Node globals, and a global "node" types entry would legitimize that. Tests that read
// repo fixtures (styles.contract.test.ts) get exactly the one signature they use.
declare module "node:fs" {
  export function readFileSync(path: URL | string, encoding: "utf8"): string;
}
