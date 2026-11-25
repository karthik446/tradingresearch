"""The week-5 labs' offline guard: every lab check (labs/w5/conftest.py) and observe install it before any learner code
is imported, for the whole process.

The week-5 checks send the ablation's requests through the real OpenRouter adapter, whose httpx client carries an
`httpx.MockTransport` that answers with the recorded analyze-3 reply (tools/fakea.py). So httpx client sends
stay allowed, and the guard sits one level down, on the transports that would reach the network: httpx
HTTPTransport.handle_request and AsyncHTTPTransport.handle_async_request. It also replaces socket connect, connect_ex,
sendto and sendmsg; socket.create_connection and getaddrinfo; subprocess.Popen; os.system and the os exec, spawn and
fork functions. Each replacement records the attempt in `HITS` and raises `Blocked`. Code that catches `Blocked` still
leaves its attempt in `HITS`, so a check can fail an attempt the learner's code swallowed.

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
    """Raised by every guarded entry point: the week-5 labs open no connection and start no process."""


def _blocked(name: str):
    def blocked(*args, **kwargs):
        HITS.append(name)
        raise Blocked(f"{name} is blocked: the week-5 labs open no connection and start no process; the model's "
                      f"reply is replayed through the provider the ablation is given")

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

    _guard(httpx.HTTPTransport, "handle_request", "httpx.HTTPTransport.handle_request")
    _guard(httpx.AsyncHTTPTransport, "handle_async_request", "httpx.AsyncHTTPTransport.handle_async_request")
