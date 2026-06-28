"""Lazy GLM (ZhipuAI) client accessor shared by both app surfaces.

Moved verbatim from aj360_app/aj360_app/core.py. Keeps the exact env-var read
(ZHIPU_API_KEY) and the thread-safe lazy singleton. Behavior parity is the
contract — do NOT change the logic.
"""
from __future__ import annotations

import os
import threading

# ---- LLM client (ZhipuAI / GLM) ---- #
_llm_client = None
_llm_lock = threading.Lock()


def get_llm_client():
    global _llm_client
    with _llm_lock:
        if _llm_client is None:
            from zhipuai import ZhipuAI
            _llm_client = ZhipuAI(api_key=os.getenv("ZHIPU_API_KEY"))
        return _llm_client
