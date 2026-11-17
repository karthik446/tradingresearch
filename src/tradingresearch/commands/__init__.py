"""The command table (REPO-PLAN §2.3): a new command is a module here exposing `register(sub)`, plus a tuple entry."""

from __future__ import annotations

from . import analyze, check, data, exp, usage

COMMANDS = (data, analyze, check, exp, usage)
