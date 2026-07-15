# Bundled fonts

- `noto-serif-latin-400.woff2`, `noto-serif-latin-600.woff2` — **Noto Serif**
  (Latin subset), © The Noto Project Authors, licensed under the **SIL Open Font
  License 1.1** (see `OFL.txt`). Source: Google Fonts / notofonts.

  It is the concrete open-source tail of the `--font-serif` fallback chain in
  `src/styles.css`, so a refined serif renders on any platform even when no system
  serif is installed.

The proprietary **"Anthropic Serif"** family (and its `Anthropic Serif Fallback *`
metric fonts) is **not** bundled here — it is only referenced by name in the CSS
fallback stack and is used solely when the viewer's OS already has it installed.
