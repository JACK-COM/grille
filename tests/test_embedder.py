"""Grille's embed settings: its own section, the environment, and the legacy move."""
import contextlib
import io
import json
import os
import unittest
from pathlib import Path

from tests.harness import GrilleCase
from grille import main  # noqa: E402
import _embed as embed  # noqa: E402
import _settings as panoply  # noqa: E402
from grillelib.config import load, write_manifest, apply_embed, legacy_note, manifest_findings, migrate_embed  # noqa: E402


class EmbedderTest(GrilleCase):
    """Grille's own embed section over the global one, under the environment, the guarded
    move of an older grille.json's embed section, and refused foreign flags."""

    def test_embed_settings(self):
        """Every layer of the embed settings, end to end."""
        with contextlib.ExitStack() as stack:
            stack.enter_context(embed.settings(**{n: getattr(embed, n) for n in ("MODEL", "OLLAMA", "AUTOSTART", "VENV")}))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            stack.enter_context(contextlib.redirect_stderr(io.StringIO()))
            cfg = panoply.path()
            cfg.parent.mkdir(parents=True, exist_ok=True)
            write_manifest({"embed": {"venv": "/old/v", "model": "m-old", "colour": "x"}})
            self.assertEqual(apply_embed()["model"], ("m-old", "grille.json"), "an older grille.json model was ignored")
            # a venv runs code on import, so only a person names one: the old file's is not read
            self.assertNotEqual(apply_embed()["venv"][1], "grille.json", "an older grille.json venv took effect")
            self.assertTrue(legacy_note() and not manifest_findings(), manifest_findings())
            # an unreadable shared file: nothing moves, nothing is overwritten
            cfg.write_text('{"embed": {"model": "x",}}')
            self.assertTrue("stay put" in migrate_embed() and load().get("embed") and cfg.read_text() == '{"embed": {"model": "x",}}')
            try:
                main(["configure", "embedder", "--model", "m-all"])
                self.fail("a write over an unreadable file went ahead")
            except SystemExit as e:
                self.assertIn("--reset", str(e.code), e.code)
            cfg.unlink()
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertTrue(main(["migrate"]) == 0 and "moved" in out.getvalue(), out.getvalue())
            self.assertNotIn("embed", load(), "the older embed section was not moved")
            with contextlib.redirect_stdout(out):
                main(["migrate"])
            self.assertTrue(out.getvalue().endswith("migrate: nothing pending\n"), "a second migrate did work")
            main(["configure", "embedder", "--model", "m-all", "--global"])
            self.assertEqual(panoply.load()[0], {"embed": {"model": "m-all"}, "grille": {"embed": {"model": "m-old"}}}, panoply.load())
            main(["configure", "embedder", "--model", "m-own", "--no-autostart"])
            got = apply_embed()
            self.assertTrue(got["model"] == ("m-own", "grille") and got["venv"][1] != "grille", got)
            main(["configure", "embedder", "--autostart", "default"])
            self.assertNotIn("autostart", panoply.load()[0]["grille"]["embed"], "--autostart default did not clear it")
            os.environ["PANOPLY_VENV"] = "/env/v"
            try:
                self.assertEqual(apply_embed()["venv"], (Path("/env/v"), "env PANOPLY_VENV"), "grille's venv beat the environment")
            finally:
                del os.environ["PANOPLY_VENV"]
            main(["configure", "embedder", "--model", "default"])
            self.assertEqual(apply_embed()["model"], ("m-all", "global"))
            cfg.write_text(json.dumps({**panoply.load()[0], "locket": {"embd": {}}}))
            main(["configure", "embedder", "--reset"])      # another piece's typo blocks nothing
            self.assertEqual(panoply.load()[0], {"embed": {"model": "m-all"}, "locket": {"embd": {}}}, panoply.load())
            for argv, flag in ((["embedder", "--withhold", "0.4"], "--withhold"), (["relay", "--global"], "--global"),
                               (["score", "--model", "x"], "--model")):
                try:
                    main(["configure", *argv])
                    self.fail(f"{flag} was ignored")
                except SystemExit as e:
                    self.assertIn(flag, str(e.code), e.code)
            cfg.unlink()


if __name__ == "__main__":
    unittest.main()
