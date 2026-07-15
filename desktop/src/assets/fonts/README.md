# Bundled fonts

- `noto-serif-latin-400.woff2`, `noto-serif-latin-600.woff2` — **Noto Serif**
  (Latin subset), © The Noto Project Authors, licensed under the **SIL Open Font
  License 1.1** (see `OFL.txt`). Source: Google Fonts / notofonts.

  It is the concrete open-source tail of the `--font-serif` fallback chain in
  `src/styles.css`, so a refined serif renders on any platform even when no system
  serif is installed.

The **"Anthropic Serif"** family (the product's primary typeface) IS now bundled,
at the project owner's direction, under [`anthropic/`](./anthropic/) — see that
folder's `README.md` for the weights, wiring, and a licensing note (it is a
proprietary face, unlike the OFL Noto Serif here). Noto Serif remains the open
fallback so a quality serif renders even if the Anthropic faces fail to load.
