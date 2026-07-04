"""Incremental extraction of artifact content from streaming tool-call JSON arguments."""
from ocd_core.artifact_stream import ArtifactArgStream, _decode_partial


def _drive(stream: ArtifactArgStream, fragments: list[str]):
    """Feed accumulated fragments; collect (opens, ''.join(deltas))."""
    buf, opens, content = "", [], ""
    for f in fragments:
        buf += f
        meta, delta = stream.feed(buf)
        if meta:
            opens.append(meta)
        content += delta
    return opens, content


def test_create_streams_content_incrementally():
    s = ArtifactArgStream("create_artifact", "call_1")
    frags = ['{"title":"My ', 'Doc","kind":"markdown",', '"content":"Hello', ' world"}']
    opens, content = _drive(s, frags)
    assert len(opens) == 1
    assert opens[0] == {"id": "call_1", "title": "My Doc", "kind": "markdown", "language": ""}
    assert content == "Hello world"


def test_open_emitted_exactly_once():
    s = ArtifactArgStream("create_artifact", "c1")
    opens, _ = _drive(s, ['{"title":"T","kind":"html","content":"a', 'b', 'c"}'])
    assert len(opens) == 1


def test_content_arriving_in_one_chunk():
    s = ArtifactArgStream("create_artifact", "c1")
    opens, content = _drive(s, ['{"title":"T","kind":"code","language":"python","content":"print(1)"}'])
    assert opens[0]["language"] == "python"
    assert content == "print(1)"


def test_update_uses_the_args_id_not_the_call_id():
    s = ArtifactArgStream("update_artifact", "call_99")
    opens, content = _drive(s, ['{"id":"art1",', '"content":"v2 ', 'body"}'])
    assert opens[0]["id"] == "art1"  # the target artifact, not the tool-call id
    assert opens[0]["kind"] == ""  # updates don't restate the kind
    assert content == "v2 body"


def test_update_waits_for_the_id_before_opening():
    s = ArtifactArgStream("update_artifact", "c1")
    # content key appears before the id is complete -> no open yet
    _, _ = _drive(s, ['{"content":"partial'])
    assert s._opened is False


def test_decodes_json_escapes_in_content():
    s = ArtifactArgStream("create_artifact", "c1")
    _, content = _drive(s, ['{"title":"T","kind":"markdown","content":"line1\\nline2\\t\\"q\\""}'])
    assert content == 'line1\nline2\t"q"'


def test_holds_back_partial_escape_at_edge():
    # A backslash split across fragments must not be mis-decoded.
    s = ArtifactArgStream("create_artifact", "c1")
    buf = '{"title":"T","kind":"markdown","content":"a\\'
    _, d1 = s.feed(buf)
    assert d1 == "a"  # the lone trailing backslash is held back
    buf += 'nb"}'
    _, d2 = s.feed(buf)
    assert d2 == "\nb"  # \n now decoded, then b


def test_decode_partial_unicode_escape():
    decoded, complete = _decode_partial('\\u0041B"', 0)
    assert decoded == "AB" and complete is True
    # truncated \u at the edge is held back
    decoded2, complete2 = _decode_partial("x\\u004", 0)
    assert decoded2 == "x" and complete2 is False


def test_no_content_key_yet_yields_nothing():
    s = ArtifactArgStream("create_artifact", "c1")
    meta, delta = s.feed('{"title":"T","kind":"html"')
    assert meta is None and delta == ""


def test_keys_in_unexpected_order():
    s = ArtifactArgStream("create_artifact", "c1")
    opens, content = _drive(s, ['{"content":"body","title":"T","kind":"svg"}'])
    # content came first; open still fires (title/kind resolve as they arrive on the same buffer)
    assert opens[0]["id"] == "c1"
    assert content == "body"
