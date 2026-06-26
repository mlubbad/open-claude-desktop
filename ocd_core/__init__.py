"""ocd_core — framework-agnostic core shared by the Chainlit (app.py) and
Reflex (aj360_app) surfaces of Open Claude Desktop.

Extraction is incremental (audit issue #3); the first module is the read-only
SQL guard, which was previously duplicated and divergent across the two apps.
"""
