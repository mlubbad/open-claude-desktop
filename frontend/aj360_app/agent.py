"""Compatibility shim: the agent loop now lives in ``ocd_core.agent``.

The Reflex UI (``state.py``) does ``from . import agent`` and calls
``agent.run_turn(...)`` / ``agent._strip_answer_label(...)``. Re-export the
public API plus the one underscore-prefixed name the UI references so those
call sites keep working unchanged.
"""
from ocd_core.agent import *  # noqa: F401,F403
from ocd_core.agent import _strip_answer_label  # noqa: F401
