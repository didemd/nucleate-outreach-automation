"""Senders. Milestone 1 contains ONLY a simulated sender: no network, no real email."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from .approval import ApprovalError, ApprovalService
from .drafts import Draft, Status, now_iso


class SendBlocked(Exception):
    """Raised when a draft is not allowed to be sent."""


@dataclass(frozen=True)
class SendResult:
    draft_id: str
    recipient: str
    success: bool
    detail: str


class Sender(ABC):
    """Common checks live here so every future sender (e.g. Gmail) inherits them."""

    def __init__(self, approvals: ApprovalService, ledger_path: str | Path) -> None:
        self._approvals = approvals
        self._ledger_path = Path(ledger_path)

    # --- ledger: permanent record of what was sent, used to prevent duplicates ---
    def _ledger_entries(self) -> list[dict]:
        if not self._ledger_path.exists():
            return []
        with open(self._ledger_path, encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]

    def _already_sent(self, draft: Draft) -> bool:
        recipient = draft.recipient.strip().lower()
        return any(
            e["success"] and e["campaign_id"] == draft.campaign_id and e["recipient"] == recipient
            for e in self._ledger_entries()
        )

    def has_success_record(self, draft_id: str) -> bool:
        """True if the ledger holds a successful delivery for this draft (used for crash recovery)."""
        return any(e["success"] and e["draft_id"] == draft_id for e in self._ledger_entries())

    def _record(self, draft: Draft, success: bool, detail: str, simulated: bool) -> None:
        self._ledger_path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "time": now_iso(),
            "draft_id": draft.draft_id,
            "campaign_id": draft.campaign_id,
            "recipient": draft.recipient.strip().lower(),
            "fingerprint": draft.fingerprint,
            "approved_by": draft.approval.reviewer if draft.approval else None,
            "success": success,
            "simulated": simulated,
            "detail": detail,
        }
        with open(self._ledger_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def _check_allowed(self, draft: Draft) -> None:
        if draft.status is Status.SENT:
            raise SendBlocked("Draft was already sent")
        try:
            self._approvals.verify(draft)
        except ApprovalError as exc:
            raise SendBlocked(f"Blocked: {exc}") from exc
        if self._already_sent(draft):
            raise SendBlocked(f"Blocked: {draft.recipient} already received this campaign")

    def send(self, draft: Draft) -> SendResult:
        self._check_allowed(draft)
        return self._deliver(draft)

    @abstractmethod
    def _deliver(self, draft: Draft) -> SendResult:
        """Perform the delivery. Only called after all checks passed."""


class SimulatedSender(Sender):
    """Pretends to send. Optionally fails for chosen addresses to test error handling."""

    def __init__(self, approvals: ApprovalService, ledger_path: str | Path,
                 fail_for: set[str] | None = None) -> None:
        super().__init__(approvals, ledger_path)
        self._fail_for = {a.lower() for a in (fail_for or set())}

    def _deliver(self, draft: Draft) -> SendResult:
        if draft.recipient.strip().lower() in self._fail_for:
            detail = "Simulated delivery failure"
            draft.transition(Status.FAILED)
            self._record(draft, False, detail, simulated=True)
            return SendResult(draft.draft_id, draft.recipient, False, detail)
        detail = "Simulated send (no email was transmitted)"
        draft.transition(Status.SENT)
        self._record(draft, True, detail, simulated=True)
        return SendResult(draft.draft_id, draft.recipient, True, detail)
