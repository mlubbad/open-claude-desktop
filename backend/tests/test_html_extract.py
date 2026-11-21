"""HTML → text extraction for web_fetch: boilerplate/comment removal, entity decoding,
and block-tag → newline conversion, while preserving the main content."""
from ocd_core import integrations


def test_strips_boilerplate_and_keeps_content():
    html = """
    <html><head><title>T</title><style>.x{color:red}</style></head>
    <body>
      <header>Site nav here</header>
      <nav>Menu Home About</nav>
      <article><h1>Real Title</h1><p>The important content.</p></article>
      <aside>Ad column</aside>
      <form><button>Subscribe</button></form>
      <footer>© 2026</footer>
      <script>tracker()</script>
    </body></html>
    """
    out = integrations._html_to_text(html)
    assert "Real Title" in out
    assert "The important content." in out
    # Chrome/boilerplate is gone.
    for junk in ("Site nav here", "Menu Home About", "Ad column", "Subscribe",
                 "© 2026", "tracker()", "color:red"):
        assert junk not in out


def test_strips_html_comments():
    out = integrations._html_to_text("<p>Visible<!-- hidden note -->text</p>")
    assert "hidden note" not in out
    assert "Visible" in out and "text" in out


def test_decodes_entities():
    out = integrations._html_to_text("<p>Tom &amp; Jerry &lt;3</p>")
    assert "Tom & Jerry <3" in out


def test_block_tags_become_newlines():
    out = integrations._html_to_text("<p>one</p><p>two</p>")
    assert "one" in out and "two" in out
    assert "\n" in out  # paragraphs are separated


def test_collapses_whitespace():
    out = integrations._html_to_text("<div>a\n\n\n\n   b</div>")
    assert "a" in out and "b" in out
    assert "\n\n\n" not in out  # runs of blank lines collapsed
