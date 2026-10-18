"""Where the app keeps its files and where the approval key comes from.

Everything private (database, ledger, .env) lives outside Git: the data
folder and .env are listed in .gitignore.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Single-user local prototype: review records are labelled with this fixed name.
# It is a label only, NOT a login or a verified identity.
LOCAL_OPERATOR = "Local operator (unverified)"


def load_dotenv(path: Path) -> dict[str, str]:
    """Tiny .env reader (KEY=value lines). Avoids adding a dependency."""
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip("\"'")
    return values


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    approval_key: str | None

    @property
    def db_path(self) -> Path:
        return self.data_dir / "outreach.db"

    @property
    def ledger_path(self) -> Path:
        return self.data_dir / "sent_ledger.jsonl"

    @classmethod
    def load(cls, root: Path | None = None) -> "Settings":
        root = ROOT if root is None else root  # looked up at call time so tests can redirect it
        file_values = load_dotenv(root / ".env")

        def get(name: str) -> str | None:
            return os.environ.get(name) or file_values.get(name) or None

        data_dir = Path(get("OUTREACH_DATA_DIR") or root / "data")
        return cls(data_dir=data_dir, approval_key=get("OUTREACH_APPROVAL_KEY"))
