"""The store: each session's withheld spans and fetched files, in a directory of its own
that a later call sweeps once it is a week old.
"""
import os
import shutil
import tempfile
import time
from pathlib import Path


STORE_DAYS = 7           # a session's store outlives it by this much, then the next call sweeps it


def store_root():
    return Path(os.environ.get("TMPDIR") or tempfile.gettempdir()) / "grille"


def store_dir():
    """Per-session store for withheld spans. Outside Claude Code set GRILLE_SESSION, or the
    `default` store is shared by every ad hoc run; every store is swept after STORE_DAYS."""
    sid = os.environ.get("GRILLE_SESSION") or os.environ.get("CLAUDE_CODE_SESSION_ID") or "default"
    root = store_root()
    d = root / sid
    d.mkdir(parents=True, exist_ok=True)
    d.chmod(0o700)   # withheld spans are the most sensitive bytes the tool touches
    cutoff = time.time() - STORE_DAYS * 86400
    for old in root.iterdir():
        if old.is_dir() and old != d and old.stat().st_mtime < cutoff:
            shutil.rmtree(old, ignore_errors=True)
    return d
