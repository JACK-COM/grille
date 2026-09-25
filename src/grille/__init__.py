"""Grille as a library under a pip or uv install: `from grille import acquire, screen`."""
from .grille import (  # noqa: F401
    __version__, acquire, cli, fetch, main, rank, rank_each, reasons_for, relay_settings, score_pages,
    score_settings, score_text, screen, store_dir, verify,
)
