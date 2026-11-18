"""The vector cache: each sub-chunk's embedding kept on disk by the embedder's space and the
text, so a refetched page, or a new question about a page already read, costs no embedding.
A 1,532-page manual took 105 s to embed and is read again for every question asked of it.

One SQLite file under the Grille home, opened per run; at more than ROWS_CAP vectors the
oldest tenth go. A cache that will not open is no cache: ranking embeds as before.
"""
import sqlite3
from pathlib import Path
from typing import Any, Optional

import numpy as np

ROWS_CAP = 400_000        # about 1.2 GB of 768-wide float32 vectors at most


class VectorCache:
    """A mapping from embed.cache_key to a vector, as embed.embed(cache=) reads and writes it."""

    def __init__(self, path: Path):
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), timeout=5)
        self.db.execute("CREATE TABLE IF NOT EXISTS v (k TEXT PRIMARY KEY, vec BLOB)")
        self.added = 0

    def get(self, key: str, default: Any = None) -> Optional[Any]:
        row = self.db.execute("SELECT vec FROM v WHERE k = ?", (key,)).fetchone()
        return np.frombuffer(row[0], dtype=np.float32) if row else default

    def __setitem__(self, key: str, vec: Any) -> None:
        self.db.execute("INSERT OR REPLACE INTO v VALUES (?, ?)", (key, np.asarray(vec, dtype=np.float32).tobytes()))
        self.added += 1

    def close(self) -> None:
        try:
            if self.added:
                n = self.db.execute("SELECT COUNT(*) FROM v").fetchone()[0]
                if n > ROWS_CAP:
                    self.db.execute("DELETE FROM v WHERE rowid IN (SELECT rowid FROM v ORDER BY rowid LIMIT ?)",
                                    (n // 10,))
            self.db.commit()
        finally:
            self.db.close()


def open_cache(home: Path) -> Optional[VectorCache]:
    try:
        return VectorCache(home / "cache" / "vectors.sqlite")
    except (sqlite3.Error, OSError):
        return None
