"""Which account the app sends from, and how sure we are about it.

Today nothing is connected, so there is exactly one answer: "Not connected".
The shape below is what a later Google Workspace sign-in will fill in. The
important rule is that an address is only ever shown as the sender if it came
from a verified connection, never from something a person typed into a box.
"""

from __future__ import annotations

from dataclasses import dataclass

NOT_CONNECTED_TEXT = "Not connected — simulated sending only."


@dataclass(frozen=True)
class SenderIdentity:
    email: str | None = None            # verified address; None until an account is connected
    connected: bool = False
    sending_mode: str = "Simulated (no email is ever sent)"
    last_verified_at: str | None = None  # ISO time of the last successful verification

    @property
    def headline(self) -> str:
        if not self.connected or not self.email:
            return NOT_CONNECTED_TEXT
        return f"Connected as {self.email}"


def current_sender_identity() -> SenderIdentity:
    """The one place a future Gmail/Google Workspace connection plugs in."""
    return SenderIdentity()
