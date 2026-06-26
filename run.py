"""Chainlit launcher that avoids nest_asyncio on Python 3.14+."""
import sys

import nest_asyncio

if sys.version_info >= (3, 14):
    nest_asyncio.apply = lambda: None

from chainlit.cli import cli

if __name__ == "__main__":
    cli()
