import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

// node:fs is typed by test/node-builtins.d.ts (no @types/node in this webview app).
// Vite's `?raw` import is NOT an option: vitest stubs .css modules (query string
// included) to empty strings.

// Layout regression contract for styles.css. jsdom computes no layout, so the
// load-bearing rules behind real UI bugs are pinned here as text: each entry below
// broke the app once (composer overflow with DevTools open, model mega-menu clipped
// at the viewport top, menus painting over modals). Removing one regresses a bug.

const css = readFileSync(new URL("./styles.css", import.meta.url), "utf8").replace(
  /\/\*[\s\S]*?\*\//g,
  "",
);

// All declaration bodies for a selector (concatenated), including rules whose selector
// list contains it and rules nested inside @media blocks.
function rule(selector: string): string {
  const bodies: string[] = [];
  let i = 0;
  const scan = (end: number) => {
    while (i < end) {
      const open = css.indexOf("{", i);
      if (open === -1 || open >= end) break;
      const head = css.slice(i, open).trim();
      // find the matching close brace
      let depth = 1;
      let j = open + 1;
      while (j < end && depth > 0) {
        if (css[j] === "{") depth += 1;
        else if (css[j] === "}") depth -= 1;
        j += 1;
      }
      if (head.startsWith("@media") || head.startsWith("@supports")) {
        const saved = i;
        i = open + 1;
        scan(j - 1); // recurse into the block's rules
        i = saved;
      } else if (head.split(",").map((s) => s.trim()).includes(selector)) {
        bodies.push(css.slice(open + 1, j - 1));
      }
      i = j;
    }
  };
  scan(css.length);
  return bodies.join("\n");
}

describe("styles.css layout contract", () => {
  it("composer control row wraps instead of overflowing at narrow widths", () => {
    expect(rule(".composer-row")).toMatch(/flex-wrap:\s*wrap/);
  });

  it("composer trailing controls wrap as one right-aligned unit", () => {
    const r = rule(".composer-actions");
    expect(r).toMatch(/margin-left:\s*auto/);
    expect(r).toMatch(/min-width:\s*0/);
  });

  it("the model pill truncates long model ids instead of growing the pill", () => {
    expect(rule(".composer-pill.model")).toMatch(/min-width:\s*0/);
    const name = rule(".model-name");
    expect(name).toMatch(/text-overflow:\s*ellipsis/);
    expect(name).toMatch(/white-space:\s*nowrap/);
  });

  it("the model mega-menu is height-capped and never wider than the window", () => {
    const pop = rule(".mp-pop");
    expect(pop).toMatch(/max-height:\s*min\(/);
    expect(pop).toMatch(/width:\s*min\(520px,\s*calc\(100vw/);
    expect(pop).not.toMatch(/min-width:\s*520px/);
    expect(rule(".mp-col")).toMatch(/min-width:\s*0/);
  });

  it("full-screen overlays sit on the modal z tier, above in-page menus", () => {
    // In-page menus use z-index 40-45; modal-tier overlays must beat them.
    for (const sel of [".settings-overlay", ".palette-overlay", ".modal-overlay"]) {
      const z = rule(sel).match(/z-index:\s*(\d+)/);
      expect(z, `${sel} needs an explicit z-index`).not.toBeNull();
      expect(Number(z?.[1]), `${sel} must sit above menus (z>=60)`).toBeGreaterThanOrEqual(60);
    }
  });

  it("the provider model list ships its search + expander affordances", () => {
    expect(rule(".model-search")).not.toBe("");
    expect(rule(".model-more")).not.toBe("");
  });
});

// The app is a fixed-viewport shell, not a scrolling document: the transcript is the
// only thing that scrolls. This broke once — in a short or narrow window the composer
// was pushed past the viewport, so the DOCUMENT grew a scrollbar of its own on top of
// the transcript's ("scroll above scroll"), and scrolling it slid the whole app up so
// transcript content ran underneath the footer. Each rule below holds that shut.
describe("styles.css app-shell scroll containment", () => {
  it("locks the document so only inner regions scroll", () => {
    for (const sel of ["html", "body", "#root"]) {
      expect(rule(sel), `${sel} must be pinned to the viewport`).toMatch(/height:\s*100%/);
    }
    for (const sel of ["html", "body"]) {
      expect(rule(sel), `${sel} must not scroll`).toMatch(/overflow:\s*hidden/);
    }
  });

  it("clips the shell so nothing can escape into the document", () => {
    const shell = rule(".app-shell");
    expect(shell).toMatch(/overflow:\s*hidden/);
    // 100vh ignores a horizontal scrollbar and any browser/OS chrome; 100% tracks the
    // real box the shell was given.
    expect(shell).toMatch(/height:\s*100%/);
    expect(shell).not.toMatch(/height:\s*100vh/);
  });

  it("lets every column in the chat layout shrink below its content", () => {
    // Without min-height:0 a flex column refuses to shrink past its content's
    // min-content height, so the overflow lands on the document instead of the
    // transcript. .transcript also needs it despite overflow-y:auto — its padding
    // otherwise floors the box and pushes the footer out of view.
    for (const sel of [".app", ".workarea", ".chat-col", ".transcript"]) {
      expect(rule(sel), `${sel} needs min-height: 0`).toMatch(/min-height:\s*0/);
    }
  });

  it("compacts the composer in short windows so it never needs to escape", () => {
    // The footer's optional chrome yields before the layout does.
    expect(rule(".footer-note")).toMatch(/display:\s*none/);
  });

  it("keeps the composer's popovers unclipped by never scrolling the footer", () => {
    // .tools-menu / .mp-pop open upward out of the footer; an overflow container here
    // would cut them off. The transcript above absorbs the space instead.
    expect(rule(".footer")).not.toMatch(/overflow/);
  });

  it("centres the empty-state hero with margin:auto, not align-items:center", () => {
    // align-items:center on an overflowing scroll container puts the top of the content
    // above the scroll origin, where it can never be reached.
    expect(rule(".hero")).not.toMatch(/align-items:\s*center/);
    expect(rule(".hero-inner")).toMatch(/margin:\s*auto/);
  });
});
