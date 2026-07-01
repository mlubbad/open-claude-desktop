"""Persist per-conversation tool/capability selection."""
from __future__ import annotations


def test_conversation_model_has_tools_default_empty():
    from ocd_core.db.models import Conversation
    c = Conversation(id="c1", project_id="p", title="T")
    assert c.tools == {}


def test_save_and_get_conversation_roundtrips_tools(db):
    from ocd_core import conversations
    conversations.create_conversation("p", "hi")
    convs = conversations.list_conversations("p")
    cid = convs[0]["id"]
    tools = {"mcp": ["playwright"], "bigquery": True, "web_fetch": True}
    conversations.save_conversation("p", cid, [{"role": "user", "content": "x", "kind": "user"}],
                                    title="T", tools=tools)
    got = conversations.get_conversation("p", cid)
    assert got["tools"] == tools
