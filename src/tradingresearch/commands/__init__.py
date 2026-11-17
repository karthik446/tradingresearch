"""The command table (REPO-PLAN §2.3): a new command is a module here exposing `register(sub)`, plus a tuple entry."""

from __future__ import annotations

from . import analyze, check, daily, data, exp, news, reconcile, screen, thesis, usage

COMMANDS = (data, news, screen, analyze, thesis, reconcile, daily, check, exp, usage)
