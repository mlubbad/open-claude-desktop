# Anthropic Serif (bundled)

These `.woff2` files are the **Anthropic Serif** typeface, provided by the project
owner and converted from the supplied OpenType (`.otf`) sources to WOFF2 (the app
is a webview; WOFF2 is far smaller and is what `@font-face` wants).

Two optical sizes are shipped, wired in `src/styles.css`:

- **Text** — body / UI. Weights 400, 500, 600, 700 + 400 italic.
  Exposed as the `--font-serif` custom property (first family in the stack).
- **Display** — large headings (greeting, project/modal titles). Weights 400, 600.
  Exposed as `--font-display`.

| File | Family | Weight | Style |
|------|--------|--------|-------|
| `anthropic-serif-text-400.woff2`        | Anthropic Serif         | 400 | normal |
| `anthropic-serif-text-400-italic.woff2` | Anthropic Serif         | 400 | italic |
| `anthropic-serif-text-500.woff2`        | Anthropic Serif         | 500 | normal |
| `anthropic-serif-text-600.woff2`        | Anthropic Serif         | 600 | normal |
| `anthropic-serif-text-700.woff2`        | Anthropic Serif         | 700 | normal |
| `anthropic-serif-display-400.woff2`     | Anthropic Serif Display | 400 | normal |
| `anthropic-serif-display-600.woff2`     | Anthropic Serif Display | 600 | normal |

## Licensing

Anthropic Serif is a **proprietary** typeface (unlike the open-licensed Noto Serif
in the parent directory). It is bundled here at the project owner's direction from
owner-supplied files. Redistribution rights differ from an OFL/open font — if this
repository or the packaged app is distributed publicly, confirm the font's license
permits it, or swap the default to an open family (the picker already offers Noto
Serif, and `--font-serif` falls back to it automatically).
