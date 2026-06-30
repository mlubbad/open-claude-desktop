"""Guard: the GLM accessor requires the zhipuai *v2* API (the ZhipuAI class).

Regression test for the dependency conflict where an unpinned `zhipuai` resolved
to v1.0.7 (which has no `ZhipuAI` class) because `mcp`'s `pyjwt[crypto]>=2.10.1`
floor collides with zhipuai 2.x's `pyjwt<2.9.0` pin. The agent turn then crashed
with: cannot import name 'ZhipuAI' from 'zhipuai'.
"""
from __future__ import annotations


def test_zhipuai_exposes_v2_client_class():
    # v1.0.7 lacks this symbol; the agent's get_llm_client() depends on it.
    from zhipuai import ZhipuAI

    assert ZhipuAI is not None


def test_get_llm_client_builds_v2_client(monkeypatch):
    from zhipuai import ZhipuAI

    from ocd_core import llm

    monkeypatch.setenv("ZHIPU_API_KEY", "test-id.test-secret")
    llm._llm_client = None  # reset the lazy singleton between cases
    client = llm.get_llm_client()
    assert isinstance(client, ZhipuAI)
