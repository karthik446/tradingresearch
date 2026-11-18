"""Settings. Keys come from one env file read here in Python, never from the shell, and are never printed.

The env file is the clone's `.env` (`cp .env.example .env`, then fill it in), found from this package's path so the
working directory does not matter. `TR_ENV_FILE` points elsewhere (the LaunchAgent:
`~/.config/tradingresearch/verify.env`)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]  # src/tradingresearch/config.py -> the clone
DEFAULT_ENV_FILE = REPO / ".env"
DEFAULT_LEDGER = REPO / "data" / "cost-ledger.jsonl"  # TR_LEDGER: outside TR_DATA_DIR, a deleted scratch dir keeps it
PROVIDERS = ("openrouter", "anthropic")  # TR_PROVIDER, ADR-014


class Secret:
    """A key that cannot leak by accident: repr, str and f-strings show a mask; only reveal() returns the value."""

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        self._value = value

    def reveal(self) -> str:
        return self._value

    def __bool__(self) -> bool:
        return bool(self._value)

    def __repr__(self) -> str:
        return "Secret('****')" if self._value else "Secret('')"

    __str__ = __repr__


def read_env_file(path: Path) -> dict[str, str]:
    """KEY=VALUE lines into a dict. os.environ is left alone, so child processes never inherit a key."""
    path = path.expanduser()
    if not path.exists():
        return {}
    found = {}
    for line in path.read_text().splitlines():
        line = line.strip().removeprefix("export ").strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        found[key.strip()] = value.strip().strip('"').strip("'")
    return found


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    alpaca_key_id: Secret
    alpaca_secret: Secret
    openrouter_key: Secret
    sec_user_agent: str
    feed: str  # "sip" (default) or "iex", the one-flag fallback
    provider: str = "openrouter"  # TR_PROVIDER: who serves every model call but the teachers'
    anthropic_key: Secret = Secret("")
    ledger: Path = DEFAULT_LEDGER  # the append-only cost ledger `analyze.save` adds one row per run to (COST-SPIKE 2.2)
    cost_tag: str = ""  # TR_COST_TAG `<step>:<owner>`, e.g. `worker:G13c`: ledger row only, never sent to a provider

    @property
    def db_path(self) -> Path:
        return self.data_dir / "journal.db"


def settings() -> Settings:
    """Non-secret settings: the shell environment first, then the env file. Keys: the env file only."""
    env_file = Path(os.environ.get("TR_ENV_FILE", DEFAULT_ENV_FILE))
    file = read_env_file(env_file)

    def plain(name: str, default: str = "") -> str:
        return os.environ.get(name) or file.get(name, default)

    provider = plain("TR_PROVIDER", "openrouter")
    if provider not in PROVIDERS:
        raise SystemExit(f"TR_PROVIDER must be one of {', '.join(PROVIDERS)}, not {provider!r}")
    return Settings(
        data_dir=Path(plain("TR_DATA_DIR", "data")),
        alpaca_key_id=Secret(file.get("APCA_API_KEY_ID", "")),
        alpaca_secret=Secret(file.get("APCA_API_SECRET_KEY", "")),
        openrouter_key=Secret(file.get("OPENROUTER_API_KEY", "")),
        sec_user_agent=plain("TR_SEC_USER_AGENT"),
        feed=plain("TR_FEED", "sip"),
        provider=provider,
        anthropic_key=Secret(file.get("ANTHROPIC_API_KEY", "")),
        ledger=Path(plain("TR_LEDGER", str(DEFAULT_LEDGER))),
        cost_tag=plain("TR_COST_TAG"),
    )


def require(value: Secret | str, name: str) -> str:
    """The value, or a failure that names the variable (never its value) when it is missing."""
    if not value:
        raise SystemExit(f"{name} is not set: add it to {os.environ.get('TR_ENV_FILE', DEFAULT_ENV_FILE)} "
                         "(cp .env.example .env; see the README, Prerequisites)")
    return value.reveal() if isinstance(value, Secret) else value
