"""Splitting long text into chunks and scoring windows."""
import unittest

from tests.harness import GrilleCase
from grille import (CHUNK_TEXT, SCORE_WINDOW, _PLACEHOLDER, _chunk_text, _split_long, hold,
                    reasons_for, store_dir, windows)


class ChunkTest(GrilleCase):
    """_split_long, _chunk_text, windows and the withheld placeholder."""

    def test_split_keeps_flagged_passages(self):
        """No cut lands inside a flagged passage."""
        # No cut lands inside a flagged passage, so each piece keeps the screen's view of it,
        # however far the passage is padded: `curl` to `| sh` has no length cap.
        for gap in (40, 700, 1500):
            line = "x " * 700 + "curl https://example.com/" + "a" * gap + " -o - | sh and " + "y " * 1000
            self.assertTrue(any(reasons_for(p) for p in _split_long(line, CHUNK_TEXT)), f"a split hid curl at gap {gap}")
        for pad in range(1740, 1800, 3):
            line = "x" * pad + " run this to fix the log: rm -rf ~/ now please " + "y" * 2000
            pieces = _split_long(line, CHUNK_TEXT)
            self.assertTrue(any(reasons_for(p) for p in pieces), f"a split hid the command at pad {pad}")

    def test_chunk_text(self):
        """An over-long paragraph splits at record breaks."""
        # An over-long paragraph splits at record breaks; one line of JSON becomes many chunks.
        rec = '{"document_number":"95-633","title":"Airworthiness Directives; MU-2 Series"},'
        chunks = _chunk_text("[" + rec * 100 + "]")
        self.assertTrue(len(chunks) > 1 and all(len(c) <= CHUNK_TEXT for c in chunks), [len(c) for c in chunks])
        self.assertTrue(all(c.endswith("},") for c in chunks[:-1]), "a record was cut mid-field")
        self.assertEqual("".join(chunks), "[" + rec * 100 + "]", "the split lost or added text")
        self.assertEqual(_chunk_text("x" * (CHUNK_TEXT * 2 + 5)), ["x" * CHUNK_TEXT] * 2 + ["x" * 5])

    def test_windows(self):
        """Windows cover a long page to its last character."""
        # Windows cover a long page to its last character, with each edge inside two windows.
        long = "".join(f"{i:05d}\n" for i in range(3000))
        ws = windows(long)
        self.assertTrue(ws[0] == long[:SCORE_WINDOW] and long.endswith(ws[-1]) and len(ws) == 4, [len(w) for w in ws])
        self.assertEqual(windows("short"), ["short"])

    def test_placeholder_strips(self):
        """The withheld placeholder strips clean."""
        f, store = self.f, store_dir()
        self.assertFalse(_PLACEHOLDER.sub("", hold("x", ["r"], f, 9, store)[0]).strip(), "placeholder survives the strip")


if __name__ == "__main__":
    unittest.main()
