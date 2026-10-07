"""``--only TABLE ...`` beside a directory argument, shared by four commands.

``semantic validate <dir>``, ``semantic status <run>``, ``semantic fixed <run>`` and
``catalog digest <dir>`` each take a directory and ``--only`` with one or more tables.
``--only`` takes every word after it, so ``--only A <dir>`` used to leave the directory
missing. The directory is declared optional (:func:`add_directory`); after parsing,
:func:`take_back_directory` moves a swallowed directory back out of ``--only`` when the
last word there is a path (it holds ``/`` or names an existing directory) and at least
one table stays. Anything else is a usage error that says where to put the directory.
A table name never holds ``/``, so no table is ever taken for the directory.
"""

from __future__ import annotations

import argparse
from pathlib import Path

_KEY = "_only_directory"


def add_directory(parser: argparse.ArgumentParser, name: str, help: str) -> None:
    """The directory positional, optional so that ``--only`` may swallow it."""
    parser.add_argument(name, nargs="?", help=help)
    parser.set_defaults(**{_KEY: (name, parser)})


def add_only(parser: argparse.ArgumentParser, help: str, *, required: bool = False) -> None:
    parser.add_argument(
        "--only", nargs="+", action="extend", default=None, required=required,
        metavar="TABLE", help=help,
    )


def take_back_directory(args: argparse.Namespace) -> None:
    """Fill the directory from the end of ``--only``, or exit 2 with a usage error."""
    name, parser = getattr(args, _KEY)
    if getattr(args, name) is not None:
        return
    only = args.only or []
    if len(only) > 1 and _is_path(only[-1]):
        setattr(args, name, only.pop())
        return
    if not only:
        parser.error(f"the following arguments are required: {name}")
    parser.error(
        f"--only takes every word after it, so {name} is missing: put {name} before "
        f"--only, or end the tables with --"
    )


def _is_path(word: str) -> bool:
    return "/" in word or "\\" in word or Path(word).is_dir()
