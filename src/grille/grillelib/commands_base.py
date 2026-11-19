"""What a verb declares: its name, help, arguments and handler, the epilog its help ends
with, and whether it reminds of unfinished setup. cli.main builds the command line from the
VERBS each owning module exports, so a new verb is one declaration beside its handler."""
import argparse
from typing import Any, Callable, NamedTuple, Optional


class Verb(NamedTuple):
    name: str
    help: str
    run: Callable[[argparse.Namespace], Any]
    args: Optional[Callable[[argparse.ArgumentParser], object]] = None
    nag: bool = True                 # reminds of an unfinished setup (relay, settings) on every run
    epilog: Optional[str] = None
