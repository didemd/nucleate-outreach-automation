"""Email drafts and their life cycle (state machine)."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from .contacts import Contact
from .templating import render_email


class Status(str, Enum):
    DRAFT = "DRAFT"
    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SENT = "SENT"
    FAILED = "FAILED"


# Which status may follow which. SENT is final.
ALLOWED_TRANSITIONS: dict[Status, set[Status]] = {
    Status.DRAFT: {Status.PENDING_REVIEW},
    Status.PENDING_REVIEW: {Status.APPROVED, Status.REJECTED, Status.DRAFT},
    Status.APPROVED: {Status.SENT, Status.FAILED, Status.DRAFT},
    Status.REJECTED: {Status.DRAFT},
    Status.FAILED: {Status.DRAFT},
    Status.SENT: set(),
}


class InvalidTransition(Exception):
    pass


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def fingerprint(recipient: str, subject: str, body: str) -> str:
    """Hash of exactly what the recipient would receive.

    Changing even one character of recipient, subject or body gives a
    completely different value. JSON encoding keeps the three parts unambiguous.
    """
    payload = json.dumps([recipient.strip().lower(), subject, body], ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Approval:
    fingerprint: str
    reviewer: str
    approved_at: str
    signature: str  # HMAC created by ApprovalService; cannot be forged without the secret key


@dataclass
class Draft:
    recipient: str
    subject: str
    body: str
    campaign_id: str
    draft_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    status: Status = Status.DRAFT
    approval: Approval | None = None
    history: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        for label, value in (("recipient", self.recipient), ("subject", self.subject)):
            if "\n" in value or "\r" in value:
                raise ValueError(f"{label} must be a single line")

    @property
    def fingerprint(self) -> str:
        return fingerprint(self.recipient, self.subject, self.body)

    def _log(self, message: str) -> None:
        self.history.append(f"{now_iso()} {message}")

    def transition(self, new_status: Status) -> None:
        if new_status not in ALLOWED_TRANSITIONS[self.status]:
            raise InvalidTransition(f"Cannot go from {self.status.value} to {new_status.value}")
        self._log(f"{self.status.value} -> {new_status.value}")
        self.status = new_status

    def submit_for_review(self) -> None:
        self.transition(Status.PENDING_REVIEW)

    def edit(self, *, subject: str | None = None, body: str | None = None, recipient: str | None = None) -> None:
        """Change the content. Any approval is discarded and the draft returns to DRAFT."""
        if self.status is Status.SENT:
            raise InvalidTransition("A sent email cannot be edited")
        new_recipient = self.recipient if recipient is None else recipient
        new_subject = self.subject if subject is None else subject
        for label, value in (("recipient", new_recipient), ("subject", new_subject)):
            if "\n" in value or "\r" in value:
                raise ValueError(f"{label} must be a single line")
        self.recipient, self.subject = new_recipient, new_subject
        if body is not None:
            self.body = body
        if self.approval is not None:
            self._log("approval invalidated by edit")
        self.approval = None
        if self.status is not Status.DRAFT:
            self.transition(Status.DRAFT)


def create_draft(contact: Contact, template_text: str, sender_name: str, campaign_id: str) -> Draft:
    """Build a DRAFT from a contact. Ineligible contacts are refused."""
    if not contact.outreach_eligible:
        raise ValueError(f"{contact.email} is not eligible for outreach")
    subject, body = render_email(template_text, contact, sender_name)
    return Draft(recipient=contact.email, subject=subject, body=body, campaign_id=campaign_id)
