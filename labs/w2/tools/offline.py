"""The week-2 labs' offline guard: every lab check (labs/w2/conftest.py) and observe install it before any learner code
is imported, for the whole process.

It replaces these entry points with a function that records the attempt in `HITS` and raises `Blocked`:
socket connect, connect_ex, sendto and sendmsg; socket.create_connection and getaddrinfo; subprocess.Popen; os.system,
the os exec, spawn and fork functions; httpx Client.send and AsyncClient.send; gigai-core's ModelJudge.grade and the
grade of every gigai-core judge class. Code that catches `Blocked` still leaves its attempt in `HITS`, so a check can
fail an attempt the learner's code swallowed.

It is a guard on those entry points, not a sandbox: code that reaches the C modules (`_socket`, `_posixsubprocess`),
a ctypes call, or a library that does not go through them is not stopped. Like the rest of the labs it is an honor
system.
"""

from __future__ import annotations

import os
import socket
import subprocess

HITS: list[str] = []


class Blocked(RuntimeError):
    """Raised by every guarded entry point: the week-2 labs make no network, subprocess or model call."""


def _blocked(name: str):
    def blocked(*args, **kwargs):
        HITS.append(name)
        raise Blocked(f"{name} is blocked: the week-2 labs make no network, subprocess or model call")

    return blocked


def _guard(owner, attr: str, name: str) -> None:
    if getattr(owner, attr, None) is not None:
        setattr(owner, attr, _blocked(name))


_installed = False


def install() -> None:
    """Guard every entry point listed in the module docstring. Safe to call twice."""
    global _installed
    if _installed:
        return
    _installed = True
    for attr in ("connect", "connect_ex", "sendto", "sendmsg"):
        _guard(socket.socket, attr, f"socket.socket.{attr}")
    for attr in ("create_connection", "getaddrinfo"):
        _guard(socket, attr, f"socket.{attr}")
    _guard(subprocess.Popen, "__init__", "subprocess.Popen")
    for attr in ("system", "posix_spawn", "posix_spawnp", "fork", "forkpty", "execv", "execve", "execl", "execle",
                 "execlp", "execlpe", "execvp", "execvpe", "spawnv", "spawnve", "spawnl", "spawnle", "spawnlp",
                 "spawnlpe", "spawnvp", "spawnvpe"):
        _guard(os, attr, f"os.{attr}")

    import httpx  # noqa: PLC0415  (imported here so the guard module itself loads without the project's deps)

    _guard(httpx.Client, "send", "httpx.Client.send")
    _guard(httpx.AsyncClient, "send", "httpx.AsyncClient.send")

    from gigai_core.graders import judge  # noqa: PLC0415

    judges = [judge.ModelJudge]
    while judges:
        cls = judges.pop()
        judges.extend(cls.__subclasses__())
        if "grade" in vars(cls):
            _guard(cls, "grade", f"{cls.__name__}.grade")
