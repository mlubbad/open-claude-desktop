"""Compatibility shim — the integrations domain layer moved to ocd_core.

The implementation now lives in ``ocd_core.integrations`` (a single, verbatim
module). This shim re-exports its public surface so the Reflex surfaces
(``state.py`` / ``agent.py``), which do ``from . import integrations`` and call
``integrations.X``, keep working unchanged.
"""
from ocd_core.integrations import *  # noqa: F401,F403
