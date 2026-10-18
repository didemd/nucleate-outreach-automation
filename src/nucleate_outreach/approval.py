"""Human approval: the only code path that can produce a valid Approval."""

from __future__ import annotations

import hashlib
import hmac

from .drafts import Approval, Draft, Status, InvalidTransition, now_iso

_MIN_KEY_LENGTH = 16
_PLACEHOLDER_KEY = "change-me-to-a-long-random-string"


class ApprovalError(Exception):
    pass


class ApprovalService:
    """Creates and verifies approvals using a secret signing key."""

    def __init__(self, secret_key: str) -> None:
        if not secret_key or len(secret_key) < _MIN_KEY_LENGTH or secret_key == _PLACEHOLDER_KEY:
            raise ApprovalError(
                "A real approval key is required (at least 16 characters, not the .env.example placeholder)."
            )
        self._key = secret_key.encode("utf-8")

    def _sign(self, draft_id: str, fingerprint: str, reviewer: str) -> str:
        message = f"{draft_id}|{fingerprint}|{reviewer}".encode("utf-8")
        return hmac.new(self._key, message, hashlib.sha256).hexdigest()

    def approve(self, draft: Draft, reviewer: str) -> None:
        """Approve exactly the current recipient, subject and body."""
        if not reviewer.strip():
            raise ApprovalError("A reviewer name is required")
        if draft.status is not Status.PENDING_REVIEW:
            raise InvalidTransition(f"Only PENDING_REVIEW drafts can be approved (status is {draft.status.value})")
        fp = draft.fingerprint
        draft.approval = Approval(
            fingerprint=fp,
            reviewer=reviewer.strip(),
            approved_at=now_iso(),
            signature=self._sign(draft.draft_id, fp, reviewer.strip()),
        )
        draft.transition(Status.APPROVED)

    def reject(self, draft: Draft, reviewer: str, reason: str = "") -> None:
        if draft.status is not Status.PENDING_REVIEW:
            raise InvalidTransition(f"Only PENDING_REVIEW drafts can be rejected (status is {draft.status.value})")
        draft.approval = None
        draft.transition(Status.REJECTED)
        draft._log(f"rejected by {reviewer.strip() or 'unknown'}: {reason or 'no reason given'}")

    def verify(self, draft: Draft) -> None:
        """Raise ApprovalError unless the draft carries a genuine approval of its CURRENT content."""
        approval = draft.approval
        if approval is None:
            raise ApprovalError("No approval recorded")
        if draft.status is not Status.APPROVED:
            raise ApprovalError(f"Status is {draft.status.value}, not APPROVED")
        if approval.fingerprint != draft.fingerprint:
            raise ApprovalError("Draft was modified after approval (recipient, subject or body changed)")
        expected = self._sign(draft.draft_id, approval.fingerprint, approval.reviewer)
        if not hmac.compare_digest(expected, approval.signature):
            raise ApprovalError("Approval signature is invalid")
