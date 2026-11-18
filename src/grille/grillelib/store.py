"""The store: each session's withheld spans and fetched files, in a directory of its own
that a later call sweeps once it is a week old.
"""
import os
import re
import stat
import shutil
import tempfile
import time
from pathlib import Path


STORE_DAYS = 7           # a session's store outlives it by this much, then the next call sweeps it


SESSION = re.compile(r"[\w-]{1,64}", re.ASCII)
SPAN_ID = re.compile(r"[0-9a-f]{8}|[0-9a-f]{12}")


def store_root():
    """This user's own directory under the temp dir: macOS's is per user already, Linux's
    /tmp is shared, so another user could plant the root or link a session into theirs."""
    return Path(os.environ.get("TMPDIR") or tempfile.gettempdir()) / f"grille-{os.getuid()}"


def _owned(d):
    """`d` made if missing, refused unless it is a real directory this user owns, then 0700."""
    d.mkdir(mode=0o700, exist_ok=True)
    st = os.lstat(d)
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid():
        raise SystemExit(f"grille: {d} is not a directory this user owns; remove it and run again")
    d.chmod(0o700)
    return d


def store_dir():
    """Per-session store for withheld spans. Outside Claude Code set GRILLE_SESSION, or the
    `default` store is shared by every ad hoc run; every store is swept after STORE_DAYS."""
    sid = os.environ.get("GRILLE_SESSION") or os.environ.get("CLAUDE_CODE_SESSION_ID") or "default"
    if not SESSION.fullmatch(sid):
        raise SystemExit("grille: GRILLE_SESSION takes letters, digits, '_' and '-', at most 64")
    root = _owned(store_root())
    d = _owned(root / sid)      # withheld spans are the most sensitive bytes the tool touches
    cutoff = time.time() - STORE_DAYS * 86400
    for old in root.iterdir():
        try:
            if old.is_dir() and old != d and old.stat().st_mtime < cutoff:
                shutil.rmtree(old, ignore_errors=True)
        except OSError:
            continue                    # another run swept it first
    return d


def span_file(wid):
    """The file a withheld span's id names in this session's store; None for anything that
    is not an id Grille writes, so `grille show ../x` reads nothing outside the store."""
    return store_dir() / f"{wid}.json" if isinstance(wid, str) and SPAN_ID.fullmatch(wid) else None
