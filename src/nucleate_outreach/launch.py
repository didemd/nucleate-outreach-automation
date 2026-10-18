"""Command-line helpers.

    nucleate-dashboard            start the dashboard (local only, 127.0.0.1)
    nucleate-dashboard init-key   create .env with a fresh random approval key
"""

from __future__ import annotations

import secrets
import subprocess
import sys
from pathlib import Path

from .settings import ROOT


def init_key(root: Path = ROOT) -> int:
    env_file = root / ".env"
    if env_file.exists() and "OUTREACH_APPROVAL_KEY" in env_file.read_text(encoding="utf-8"):
        print(f"{env_file} already contains OUTREACH_APPROVAL_KEY - leaving it unchanged.")
        return 0
    with open(env_file, "a", encoding="utf-8") as handle:
        handle.write(f"OUTREACH_APPROVAL_KEY={secrets.token_hex(32)}\n")
    env_file.chmod(0o600)
    print(f"Created an approval key in {env_file} (this file is ignored by Git - never share it).")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args[:1] == ["init-key"]:
        return init_key()
    app = Path(__file__).parent / "dashboard" / "app.py"
    # --server.address 127.0.0.1 keeps the dashboard reachable from THIS computer only.
    cmd = [sys.executable, "-m", "streamlit", "run", str(app),
           "--server.address", "127.0.0.1", "--browser.gatherUsageStats", "false", *args]
    return subprocess.call(cmd)


if __name__ == "__main__":
    raise SystemExit(main())
