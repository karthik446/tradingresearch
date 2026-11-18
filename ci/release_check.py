"""The release checklist as code (REPO-PLAN Week 9, SPIKE §11): licence, README licences, disclaimer and reader
setup, the .gitignore audit, no tracked data or keys. No network, no model call, no key.

`uv run python ci/release_check.py` prints one `ok|FAIL <check>: <detail>` line per check and exits 1 on any FAIL.
`--fresh-clone` also clones HEAD into a temp dir, runs `uv sync --frozen` there (needs network), then the gate and
`pytest -q -x` with `TR_DATA_DIR` inside the temp dir, and removes the temp dir.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

LICENCES = {"MIT (code)": r"\bMIT\b", "CC BY-NC 4.0 (guide text)": r"CC BY-NC 4\.0",
            "CDLA-Permissive-2.0 (dataset)": r"CDLA-Permissive-2\.0"}
DISCLAIMER = "not financial advice"
SECTIONS = ("reference architecture", "reader setup")
READER_SETUP = ("ANTHROPIC_API_KEY", "APCA_API_KEY_ID", "US-only")
# Paths the program and the editor write; traces live under the data dir (config.py: TR_DATA_DIR, default `data`).
IGNORED = ("data/x.db", "data-dev/x", ".env", ".idea/x", "data/traces/x")
PRIVATE_DIRS = ("data/", "data-dev/")
# Secret-shaped: a key prefix followed by a key-length body, so the prefixes named in docs, the redact patterns and
# test placeholders (`APCA_API_KEY_ID=not-a-real-id`) do not count.
SECRETS = {
    "sk_ant_key": re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"),
    "sk_or_key": re.compile(r"sk-or-v1-[0-9a-f]{20,}"),
    "apca_value": re.compile(r"APCA[A-Z_-]*=[A-Za-z0-9]{8,}"),
    "aws_key_id": re.compile(r"AKIA[0-9A-Z]{16}"),
}
SHOWN = 10  # hits named per FAIL line
UNSET = ("TR_PROVIDER", "TR_ENV_FILE", "VIRTUAL_ENV")  # the clone runs as a fresh reader would: no provider, no key

Result = tuple[bool, str]


def _git(root: Path, *args: str) -> str:
    out = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    if out.returncode > 1:  # check-ignore exits 1 when nothing is ignored
        raise SystemExit(f"release_check: git {args[0]} failed in {root}: {out.stderr.strip()}")
    return out.stdout


def _named(items: list[str]) -> str:
    more = f" and {len(items) - SHOWN} more" if len(items) > SHOWN else ""
    return ", ".join(items[:SHOWN]) + more


def _readme(root: Path) -> str | None:
    path = root / "README.md"
    return path.read_text() if path.exists() else None


def sections(text: str) -> list[tuple[str, str]]:
    """(heading text, body): the lines after a heading up to the next heading of the same or a higher level; a `#`
    line inside a code fence is body, not a heading."""
    lines = text.splitlines()
    heads, fenced = [], False
    for i, line in enumerate(lines):
        if line.lstrip().startswith("```"):
            fenced = not fenced
        elif not fenced and (m := re.match(r"(#{1,6})\s+(.*)", line)):
            heads.append((i, len(m[1]), m[2].strip()))
    out = []
    for k, (i, level, title) in enumerate(heads):
        end = next((j for j, lv, _ in heads[k + 1:] if lv <= level), len(lines))
        out.append((title, "\n".join(lines[i + 1:end])))
    return out


# -- checks: each returns (ok, detail) ------------------------------------------------------------------------------


def check_license(root: Path) -> Result:
    path = root / "LICENSE"
    if not path.exists():
        return False, "LICENSE missing"
    if not path.read_text().startswith("MIT License"):
        return False, "LICENSE does not start `MIT License`"
    return True, "LICENSE is the MIT licence"


def check_readme_licences(root: Path) -> Result:
    text = _readme(root)
    if text is None:
        return False, "README.md missing"
    missing = [name for name, pattern in LICENCES.items() if not re.search(pattern, text)]
    if missing:
        return False, f"README.md does not name: {', '.join(missing)}"
    return True, "README.md names MIT (code), CC BY-NC 4.0 (guide text), CDLA-Permissive-2.0 (dataset)"


def check_disclaimer(root: Path) -> Result:
    text = _readme(root)
    if text is None:
        return False, "README.md missing"
    if not any(DISCLAIMER in para.lower() for para in re.split(r"\n\s*\n", text)):
        return False, f"README.md has no paragraph containing `{DISCLAIMER}`"
    return True, f"README.md carries a `{DISCLAIMER}` paragraph"


def check_gitignore(root: Path) -> Result:
    ignored = set(_git(root, "check-ignore", "--no-index", "--", *IGNORED).splitlines())
    unignored = [p for p in IGNORED if p not in ignored]
    if unignored:
        return False, f".gitignore does not cover: {', '.join(unignored)}"
    return True, f".gitignore covers {', '.join(IGNORED)}"


def check_tracked_data(root: Path) -> Result:
    bad = [p for p in _git(root, "ls-files", "-z").split("\0")
           if p and (Path(p).name == ".env" or p.startswith(PRIVATE_DIRS))]
    if bad:
        return False, f"tracked private files: {_named(bad)}"
    return True, "no tracked .env, data/ or data-dev/ file"


def check_secrets(root: Path) -> Result:
    """Secret-shaped strings in tracked text files, named by file, line and pattern; never the match itself."""
    hits, scanned = [], 0
    for rel in filter(None, _git(root, "ls-files", "-z").split("\0")):
        path = root / rel
        if not path.is_file():
            continue
        data = path.read_bytes()
        if b"\0" in data:
            continue  # binary
        scanned += 1
        for n, line in enumerate(data.decode("utf-8", "replace").splitlines(), 1):
            hits += [f"{rel}:{n} ({name})" for name, pattern in SECRETS.items() if pattern.search(line)]
    if hits:
        return False, f"{len(hits)} secret-shaped strings: {_named(hits)}"
    return True, f"no secret-shaped string in {scanned} tracked text files"


def check_readme_setup(root: Path) -> Result:
    text = _readme(root)
    if text is None:
        return False, "README.md missing"
    found = sections(text)
    missing = [s for s in SECTIONS if not any(s in title.lower() for title, _ in found)]
    if missing:
        return False, f"README.md has no section: {', '.join(missing)}"
    setup = "\n".join(body for title, body in found if "reader setup" in title.lower())
    absent = [word for word in READER_SETUP if word not in setup]
    if absent:
        return False, f"README.md reader setup does not name: {', '.join(absent)}"
    return True, f"README.md has Reference architecture and Reader setup ({', '.join(READER_SETUP)})"


CHECKS: dict[str, Callable[[Path], Result]] = {
    "license": check_license,
    "readme_licences": check_readme_licences,
    "disclaimer": check_disclaimer,
    "gitignore": check_gitignore,
    "tracked_data": check_tracked_data,
    "secrets": check_secrets,
    "readme_setup": check_readme_setup,
}


# -- fresh clone ----------------------------------------------------------------------------------------------------


def run(cmd: list[str], cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess:
    """One fresh-clone step, output captured (the tests stub this; nothing else in the checks runs it)."""
    return subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True)


def check_fresh_clone(root: Path) -> Result:
    """Clone HEAD into a temp dir, `uv sync --frozen`, the gate and the tests there; the temp dir is removed after."""
    print("fresh-clone: needs network for `uv sync --frozen`; no key and no model call")
    head = _git(root, "rev-parse", "HEAD").strip()
    with tempfile.TemporaryDirectory(prefix="tr-release-") as tmp:
        clone, data = Path(tmp) / "repo", Path(tmp) / "data"
        env = {k: v for k, v in os.environ.items() if k not in UNSET} | {"TR_DATA_DIR": str(data)}
        steps = [(["git", "clone", "--quiet", str(root), str(clone)], Path(tmp)),
                 (["git", "checkout", "--quiet", "--detach", head], clone),
                 (["uv", "sync", "--frozen"], clone),
                 (["uv", "run", "--frozen", "python", "ci/gate.py"], clone),
                 (["uv", "run", "--frozen", "pytest", "-q", "-x"], clone)]
        for cmd, cwd in steps:
            done = run(cmd, cwd, env)
            if done.returncode:
                last = next((ln for ln in reversed(f"{done.stdout}\n{done.stderr}".splitlines()) if ln.strip()), "")
                return False, f"`{' '.join(cmd[:4])}` exited {done.returncode}: {last.strip()[:200]}"
    return True, f"HEAD {head[:12]} in a clean clone: uv sync --frozen, ci/gate.py and pytest -q -x pass"


# -- command --------------------------------------------------------------------------------------------------------


def main(argv: list[str] | None = None, root: Path = ROOT) -> int:
    """One line per check; exit 1 when any check fails."""
    p = argparse.ArgumentParser(prog="ci/release_check.py", description=__doc__.splitlines()[0])
    p.add_argument("--fresh-clone", action="store_true",
                   help="also clone HEAD, uv sync --frozen (network), run the gate and the tests in the clone")
    args = p.parse_args(argv)
    checks = dict(CHECKS) | ({"fresh_clone": check_fresh_clone} if args.fresh_clone else {})
    failed = 0
    for name, check in checks.items():
        ok, detail = check(root)
        failed += not ok
        print(f"{'ok' if ok else 'FAIL'} {name}: {detail}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
