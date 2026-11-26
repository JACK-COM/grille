#!/usr/bin/env python3
"""grille: a long document and a question in, only the pages that answer it out, with
passages addressed to an AI agent withheld behind an id.

The entry point. What Grille is and how it is used is `grillelib/help_text.py`'s USAGE,
which `grille --help` prints; each job has its own module in grillelib/.
"""
import sys
from pathlib import Path

__version__ = "0.7.1"
HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:      # grillelib and the panoply-lib copies, installed flat or not;
    sys.path.append(str(HERE))     # appended, so a caller's own modules keep their names

from grillelib.cli import main as cli_main  # noqa: E402
# the library API, as `from grille import acquire, screen`
from grillelib.config import relay_settings, score_settings  # noqa: E402,F401
from grillelib.documents import acquire  # noqa: E402,F401
from grillelib.net import fetch, verify  # noqa: E402,F401
from grillelib.patterns import reasons_for  # noqa: E402,F401
from grillelib.rank import rank, rank_each  # noqa: E402,F401
from grillelib.score import score_pages, score_text  # noqa: E402,F401
from grillelib.screen import screen  # noqa: E402,F401
from grillelib.store import store_dir  # noqa: E402,F401


def main(argv=None, version=__version__):
    return cli_main(argv, version)


def cli():
    """The console-script entry point under pip and uv, which carry no Homebrew wrapper."""
    sys.exit(main())


if __name__ == "__main__":
    sys.exit(main())
