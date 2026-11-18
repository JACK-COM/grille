"""Uninstall in a throwaway home and temp dir."""
import argparse
import contextlib
import io
import os
import unittest

from tests.harness import GrilleCase
import _embed as embed  # noqa: E402
from grillelib.admin import cmd_uninstall  # noqa: E402


class UninstallTest(GrilleCase):
    """The venv stays while another piece is on PATH and goes with the last one; the settings are never removed."""

    def test_uninstall(self):
        """Dry run, a kept venv, then the last piece."""
        d = self.d
        h, bin_ = d / "uh", d / "ubin"
        venv, store = h / ".panoply/venv", d / f"utmp/grille-{os.getuid()}"
        for x in (venv, store / "s1", bin_, h / ".grille"):
            x.mkdir(parents=True, exist_ok=True)
        (bin_ / "locket").write_text("#!/bin/sh\n")
        (bin_ / "locket").chmod(0o755)
        keys = ("HOME", "PATH", "TMPDIR", "GRILLE_HOME", "PANOPLY_VENV", "LOCKET_VENV")
        saved = {k: os.environ.get(k) for k in keys}
        os.environ.update(HOME=str(h), PATH=str(bin_), TMPDIR=str(d / "utmp"), GRILLE_HOME=str(h / ".grille"))
        os.environ.pop("PANOPLY_VENV", None)
        os.environ.pop("LOCKET_VENV", None)
        ns = argparse.Namespace(yes=True, dry_run=False)
        try:
            with embed.settings(VENV=venv):
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    self.assertEqual(cmd_uninstall(argparse.Namespace(yes=False, dry_run=True)), 0)
                self.assertTrue(store.is_dir() and venv.is_dir(), "--dry-run removed something")
                with contextlib.redirect_stdout(out):
                    cmd_uninstall(ns)
                self.assertFalse(store.exists(), "the withheld-span store survived uninstall")
                self.assertTrue(venv.is_dir(), "the venv went while locket was still on PATH")
                self.assertIn("locket still use", out.getvalue(), "the kept venv was not explained")
                (bin_ / "locket").unlink()
                with contextlib.redirect_stdout(out):
                    cmd_uninstall(ns)
                self.assertFalse(venv.parent.exists(), "the last piece left the shared venv or ~/.panoply behind")
                self.assertTrue((h / ".grille").is_dir(), "uninstall removed the settings")
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v


if __name__ == "__main__":
    unittest.main()
