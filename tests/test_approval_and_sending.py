import dataclasses

import pytest

from nucleate_outreach.approval import ApprovalError, ApprovalService
from nucleate_outreach.drafts import InvalidTransition, Status
from nucleate_outreach.sender import SendBlocked, SimulatedSender


def test_new_draft_cannot_be_sent(draft, sender):
    with pytest.raises(SendBlocked):
        sender.send(draft)


def test_pending_draft_cannot_be_sent(pending, sender):
    with pytest.raises(SendBlocked):
        sender.send(pending)


def test_draft_cannot_skip_review(draft, approvals):
    with pytest.raises(InvalidTransition):
        approvals.approve(draft, "Reviewer")


def test_approved_draft_is_sent(approved, sender):
    result = sender.send(approved)
    assert result.success and approved.status is Status.SENT


def test_rejected_draft_cannot_be_sent(pending, approvals, sender):
    approvals.reject(pending, "Reviewer", "not relevant")
    assert pending.status is Status.REJECTED
    with pytest.raises(SendBlocked):
        sender.send(pending)


@pytest.mark.parametrize("field", ["body", "subject", "recipient"])
def test_edit_after_approval_invalidates(approved, sender, field):
    value = "other@example.org" if field == "recipient" else "changed"
    approved.edit(**{field: value})
    assert approved.status is Status.DRAFT and approved.approval is None
    with pytest.raises(SendBlocked):
        sender.send(approved)


def test_reapproval_after_edit_works(approved, approvals, sender):
    approved.edit(body="new body")
    approved.submit_for_review()
    approvals.approve(approved, "Reviewer")
    assert sender.send(approved).success


def test_silent_tampering_is_detected(approved, sender):
    approved.body += " sneaky change"  # bypasses edit()
    with pytest.raises(SendBlocked, match="modified after approval"):
        sender.send(approved)


def test_forged_status_without_approval_blocked(pending, sender):
    pending.status = Status.APPROVED
    with pytest.raises(SendBlocked, match="No approval"):
        sender.send(pending)


def test_forged_approval_blocked(approved, sender):
    approved.approval = dataclasses.replace(approved.approval, signature="0" * 64)
    with pytest.raises(SendBlocked, match="signature"):
        sender.send(approved)


def test_approval_from_other_key_blocked(approved, tmp_path):
    other = SimulatedSender(ApprovalService("a-different-secret-key-123456"), tmp_path / "l.jsonl")
    with pytest.raises(SendBlocked, match="signature"):
        other.send(approved)


def test_weak_keys_refused():
    for key in ("", "short", "change-me-to-a-long-random-string"):
        with pytest.raises(ApprovalError):
            ApprovalService(key)


def test_same_draft_cannot_be_sent_twice(approved, sender):
    sender.send(approved)
    with pytest.raises(SendBlocked, match="already sent"):
        sender.send(approved)


def test_same_recipient_blocked_across_drafts(approved, contact, approvals, sender):
    from nucleate_outreach.drafts import create_draft
    from conftest import TEMPLATE
    sender.send(approved)
    second = create_draft(contact, TEMPLATE, "Team", "camp1")
    second.submit_for_review()
    approvals.approve(second, "Reviewer")
    with pytest.raises(SendBlocked, match="already received"):
        sender.send(second)


def test_duplicate_protection_survives_restart(approved, contact, approvals, tmp_path):
    from nucleate_outreach.drafts import create_draft
    from conftest import TEMPLATE
    ledger = tmp_path / "ledger.jsonl"
    SimulatedSender(approvals, ledger).send(approved)
    second = create_draft(contact, TEMPLATE, "Team", "camp1")
    second.submit_for_review()
    approvals.approve(second, "Reviewer")
    with pytest.raises(SendBlocked):
        SimulatedSender(approvals, ledger).send(second)  # new sender object, same ledger file


def test_failed_send_recorded_and_needs_new_review(approved, approvals, tmp_path):
    sender = SimulatedSender(approvals, tmp_path / "l.jsonl", fail_for={approved.recipient})
    result = sender.send(approved)
    assert not result.success and approved.status is Status.FAILED
    with pytest.raises(SendBlocked):
        sender.send(approved)


def test_sent_draft_cannot_be_edited(approved, sender):
    sender.send(approved)
    with pytest.raises(InvalidTransition):
        approved.edit(body="too late")
