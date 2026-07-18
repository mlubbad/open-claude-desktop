"""sanitize_markdown() neutralizes exfiltration/XSS vectors in untrusted (model/DB/
web) markdown before it is rendered, while leaving ordinary markdown intact.

format.py is pure (imports only `re`), so load it by path -- no Reflex needed.
"""
import importlib.util
import os

_FMT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "ocd_app", "format.py")
_spec = importlib.util.spec_from_file_location("ocd_format", _FMT)
_fmt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_fmt)
sanitize_markdown = _fmt.sanitize_markdown


def test_remote_images_become_alt_text_only():
    assert sanitize_markdown("![pic](http://evil.test/a.png)") == "[pic]"
    assert sanitize_markdown("![p](https://evil.test/x.png)") == "[p]"
    assert sanitize_markdown("![p](//evil.test/x.png)") == "[p]"


def test_safe_images_are_kept():
    assert sanitize_markdown("![p](/local.png)") == "![p](/local.png)"
    assert sanitize_markdown("![p](data:image/png;base64,AAA)") == "![p](data:image/png;base64,AAA)"


def test_script_and_loading_html_tags_removed():
    assert "script" not in sanitize_markdown("hi <script>steal()</script> bye").lower()
    assert sanitize_markdown('<img src="http://e/x" onerror="alert(1)">') == ""
    assert sanitize_markdown("<iframe src=http://e></iframe>") == ""


def test_inline_event_handlers_and_dangerous_schemes_neutralized():
    assert "onerror" not in sanitize_markdown('<b onerror="x()">hi</b>').lower()
    assert sanitize_markdown("[x](javascript:alert(1))") == "[x](blocked:alert(1))"


def test_ordinary_markdown_is_preserved():
    assert sanitize_markdown("a < b and c > d") == "a < b and c > d"
    assert sanitize_markdown("**bold** and [link](https://safe.test)") == \
        "**bold** and [link](https://safe.test)"
    assert sanitize_markdown("| a | b |\n|---|---|\n| 1 | 2 |").startswith("| a | b |")


def test_empty_input():
    assert sanitize_markdown("") == ""
