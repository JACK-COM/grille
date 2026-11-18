"""The vector cache: each sub-chunk's embedding kept on disk by the embedder's space and the
text, so a refetched page, or a new question about a page already read, costs no embedding.
A 1,532-page manual took 105 s to embed and is read again for every question asked of it.

One SQLite file under the Grille home. New vectors are held in memory and written in one
short transaction at the end, so a second Grille run (parallel WebFetches are normal) never
waits on a write lock held through a long embed. Any SQLite failure ends the cache, never
the run: ranking embeds as if it had none. At more than ROWS_CAP vectors the oldest tenth go.
Opened and used on one thread.
"""
import sqlite3
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np

ROWS_CAP = 400_000        # about 1.2 GB of 768-wide float32 vectors at most


class VectorCache:
    """A mapping from embed.cache_key to a vector, as embed.embed(cache=) reads and writes it."""

    def __init__(self, path: Path):
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.db: Optional[sqlite3.Connection] = sqlite3.connect(str(path), timeout=5)
        try:
            self.db.execute("PRAGMA journal_mode=WAL")      # readers never wait on a writer
            self.db.execute("CREATE TABLE IF NOT EXISTS v (k TEXT PRIMARY KEY, vec BLOB)")
        except sqlite3.Error:
            self.db.close()
            raise
        self.new: Dict[str, bytes] = {}

    def get(self, key: str, default: Any = None) -> Optional[Any]:
        if key in self.new:
            return np.frombuffer(self.new[key], dtype=np.float32)
        if self.db is None:
            return default
        try:
            row = self.db.execute("SELECT vec FROM v WHERE k = ?", (key,)).fetchone()
        except sqlite3.Error:
            self._drop()
            return default
        return np.frombuffer(row[0], dtype=np.float32) if row else default

    def __setitem__(self, key: str, vec: Any) -> None:
        self.new[key] = np.asarray(vec, dtype=np.float32).tobytes()

    def _drop(self) -> None:
        if self.db is not None:
            try:
                self.db.close()
            except sqlite3.Error:
                pass
        self.db = None

    def close(self) -> None:
        if self.db is None:
            return
        try:
            if self.new:
                with self.db:                                  # one short transaction
                    self.db.executemany("INSERT OR REPLACE INTO v VALUES (?, ?)", self.new.items())
                    n = self.db.execute("SELECT COUNT(*) FROM v").fetchone()[0]
                    if n > ROWS_CAP:
                        self.db.execute("DELETE FROM v WHERE rowid IN (SELECT rowid FROM v ORDER BY rowid LIMIT ?)",
                                        (n // 10,))
        except sqlite3.Error:
            pass                                               # this run's vectors are not kept; nothing else is lost
        finally:
            self._drop()


def open_cache(home: Path) -> Optional[VectorCache]:
    try:
        return VectorCache(home / "cache" / "vectors.sqlite")
    except (sqlite3.Error, OSError):
        return None
