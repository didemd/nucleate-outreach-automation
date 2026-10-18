import sqlite3

import pytest

from nucleate_outreach.approval import ApprovalService
from nucleate_outreach.drafts import InvalidTransition, Status
from nucleate_outreach.sender import SendBlocked
from nucleate_outreach.service import PermissionDenied
from nucleate_outreach.store import (ConcurrentModification, DraftLocked, DraftStore, DuplicateDraft,
                                     StoreError)

from conftest import TEMPLATE, make_service


def approve(service, stored, reviewer="Rita"):
    return service.approve(stored.draft.draft_id, reviewer, stored.draft.fingerprint)


# ---------------------------------------------------------------- persistence
def test_drafts_survive_restart(tmp_path, two_contacts):
    first = make_service(tmp_path)
    created = first.create_drafts(two_contacts, TEMPLATE, "Team", "camp1").created
    approve(first, created[0])
    second = make_service(tmp_path)  # new objects, same files
    loaded = second.list_drafts("camp1")
    assert {s.draft.draft_id for s in loaded} == {s.draft.draft_id for s in created}
    alice = second.get(created[0].draft.draft_id)
    assert alice.draft.status is Status.APPROVED
    assert alice.draft.approval.reviewer == "Rita"
    assert second.approval_is_valid(alice) is True  # signature still verifies after reload


def test_draft_ids_are_stable_and_unique(queued, service):
    ids = [s.draft.draft_id for s in queued]
    assert len(set(ids)) == 2
    assert service.get(ids[0]).draft.draft_id == ids[0]


def test_ineligible_contacts_get_no_draft(service, contact):
    from dataclasses import replace
    report = service.create_drafts([replace(contact, outreach_eligible=False)], TEMPLATE, "T", "c")
    assert report.created == []


def test_importing_twice_does_not_duplicate_drafts(service, two_contacts, queued):
    report = service.create_drafts(two_contacts, TEMPLATE, "Team", "camp1")
    assert report.created == [] and len(report.skipped_existing) == 2
    assert len(service.list_drafts("camp1")) == 2


def test_filters(service, two_contacts, queued):
    service.create_drafts(two_contacts[:1], TEMPLATE, "Team", "camp2")
    approve(service, queued[0])
    assert service.store.campaigns() == ["camp1", "camp2"]
    assert len(service.list_drafts("camp2")) == 1
    assert [s.draft.status for s in service.list_drafts("camp1", [Status.APPROVED])] == [Status.APPROVED]
    assert service.campaign_progress("camp1")["camp1"] == {"APPROVED": 1, "PENDING_REVIEW": 1}


# ---------------------------------------------------------------- approval / rejection
def test_approval_records_reviewer_and_time(service, queued):
    stored = approve(service, queued[0], "Rita")
    assert stored.draft.status is Status.APPROVED
    assert stored.draft.approval.reviewer == "Rita" and stored.draft.approval.approved_at
    (decision,) = service.decisions(stored.draft.draft_id)
    assert (decision.kind, decision.actor) == ("APPROVED", "Rita")


def test_rejection_is_recorded_with_reason(service, queued):
    stored = service.reject(queued[0].draft.draft_id, "Rita", "off topic")
    assert stored.draft.status is Status.REJECTED
    (decision,) = service.decisions(stored.draft.draft_id)
    assert decision.kind == "REJECTED" and "off topic" in decision.detail


def test_cannot_approve_twice_or_unsubmitted(service, queued):
    approve(service, queued[0])
    with pytest.raises(InvalidTransition):
        approve(service, service.get(queued[0].draft.draft_id))


def test_reviewer_name_required(service, queued):
    with pytest.raises(ValueError):
        service.approve(queued[0].draft.draft_id, "  ", queued[0].draft.fingerprint)


def test_approval_of_stale_text_is_refused(service, queued):
    seen = queued[0].draft.fingerprint
    service.edit(queued[0].draft.draft_id, "Eve", body="Changed while the reviewer looked at the old text")
    service.submit_for_review(queued[0].draft.draft_id, "Eve")
    with pytest.raises(ConcurrentModification):
        service.approve(queued[0].draft.draft_id, "Rita", seen)


def test_without_key_approve_and_send_are_denied_but_reject_works(tmp_path, two_contacts):
    admin = make_service(tmp_path)
    created = admin.create_drafts(two_contacts, TEMPLATE, "Team", "c").created
    approve(admin, created[0])
    readonly = make_service(tmp_path, key=None)
    assert not readonly.can_approve
    with pytest.raises(PermissionDenied):
        readonly.approve(created[1].draft.draft_id, "Rita", created[1].draft.fingerprint)
    with pytest.raises(PermissionDenied):
        readonly.send(created[0].draft.draft_id)
    assert readonly.reject(created[1].draft.draft_id, "Rita").draft.status is Status.REJECTED


def test_placeholder_key_means_read_only(tmp_path):
    assert not make_service(tmp_path, key="change-me-to-a-long-random-string").can_approve


# ---------------------------------------------------------------- editing after approval
@pytest.mark.parametrize("field,value", [("subject", "New subject"), ("body", "New body"),
                                         ("recipient", "other@example.org")])
def test_any_edit_invalidates_approval_and_blocks_send(service, queued, field, value):
    approved = approve(service, queued[0])
    edited = service.edit(approved.draft.draft_id, "Eve", **{field: value})
    assert edited.draft.status is Status.DRAFT and edited.draft.approval is None
    kinds = [e.kind for e in service.decisions(approved.draft.draft_id)]
    assert kinds == ["APPROVED", "APPROVAL_INVALIDATED"]
    with pytest.raises(SendBlocked):
        service.send(approved.draft.draft_id)


def test_edit_persists_after_restart_and_needs_fresh_approval(tmp_path, two_contacts):
    first = make_service(tmp_path)
    d = first.create_drafts(two_contacts, TEMPLATE, "Team", "c").created[0]
    approve(first, d)
    first.edit(d.draft.draft_id, "Eve", body="edited")
    second = make_service(tmp_path)
    again = second.get(d.draft.draft_id)
    assert again.draft.body == "edited" and again.draft.status is Status.DRAFT
    with pytest.raises(SendBlocked):
        second.send(d.draft.draft_id)


def test_saving_unchanged_text_keeps_approval(service, queued):
    approved = approve(service, queued[0])
    same = service.edit(approved.draft.draft_id, "Eve", recipient=approved.draft.recipient,
                        subject=approved.draft.subject, body=approved.draft.body)
    assert same.draft.status is Status.APPROVED and same.version == approved.version


def test_invalid_recipient_or_multiline_subject_rejected(service, queued):
    with pytest.raises(ValueError):
        service.edit(queued[0].draft.draft_id, "Eve", recipient="not-an-email")
    with pytest.raises(ValueError):
        service.edit(queued[0].draft.draft_id, "Eve", subject="a\nb")


def test_editing_into_an_existing_recipient_is_refused(service, queued):
    with pytest.raises(DuplicateDraft):
        service.edit(queued[0].draft.draft_id, "Eve", recipient=queued[1].draft.recipient)


def test_stale_version_cannot_overwrite(service, queued):
    stale = service.get(queued[0].draft.draft_id)
    service.edit(queued[0].draft.draft_id, "Eve", body="newer")
    stale.draft.edit(body="older")
    with pytest.raises(ConcurrentModification):
        service.store.save(stale.draft, stale.version, "Eve")


# ---------------------------------------------------------------- invalid signatures / tampering
def _tamper(tmp_path, sql, params=()):
    with sqlite3.connect(tmp_path / "outreach.db") as conn:
        conn.execute(sql, params)


def test_forged_signature_blocks_send_and_shows_invalid(tmp_path, service, queued):
    approved = approve(service, queued[0])
    _tamper(tmp_path, "UPDATE drafts SET approval_signature='deadbeef' WHERE draft_id=?", (approved.draft.draft_id,))
    reloaded = service.get(approved.draft.draft_id)
    assert service.approval_is_valid(reloaded) is False
    with pytest.raises(SendBlocked, match="signature"):
        service.send(approved.draft.draft_id)
    assert service.store.attempts() == []  # nothing was even started


def test_signature_made_with_another_key_is_rejected(tmp_path, service, queued):
    pending = queued[0]
    forger = ApprovalService("a-completely-different-key-123456")
    forger.approve(pending.draft, "Mallory")
    service.store.save(pending.draft, pending.version, "Mallory")  # the store accepts it...
    with pytest.raises(SendBlocked, match="signature"):  # ...but the real key does not
        service.send(pending.draft.draft_id)


def test_content_changed_directly_in_database_blocks_send(tmp_path, service, queued):
    approved = approve(service, queued[0])
    _tamper(tmp_path, "UPDATE drafts SET body='sneaky change' WHERE draft_id=?", (approved.draft.draft_id,))
    with pytest.raises(SendBlocked, match="modified"):
        service.send(approved.draft.draft_id)


def test_database_refuses_approved_status_without_signature(tmp_path, service, queued):
    with pytest.raises(sqlite3.IntegrityError):
        _tamper(tmp_path, "UPDATE drafts SET status='APPROVED' WHERE draft_id=?", (queued[0].draft.draft_id,))


def test_unknown_status_in_database_fails_closed(tmp_path, service, queued):
    # CHECK constraint blocks unknown statuses outright
    with pytest.raises(sqlite3.IntegrityError):
        _tamper(tmp_path, "UPDATE drafts SET status='SENT_OK' WHERE draft_id=?", (queued[0].draft.draft_id,))


def test_store_cannot_set_sent_directly(service, queued):
    approved = approve(service, queued[0])
    approved.draft.transition(Status.SENT)
    with pytest.raises(StoreError, match="send workflow"):
        service.store.save(approved.draft, approved.version, "Mallory")


# ---------------------------------------------------------------- simulated sending / duplicates
def test_unapproved_draft_is_never_sent(service, queued):
    with pytest.raises(SendBlocked):
        service.send(queued[0].draft.draft_id)
    assert service.store.attempts() == []


def test_send_marks_sent_and_second_send_is_blocked(service, queued):
    approve(service, queued[0])
    result = service.send(queued[0].draft.draft_id)
    assert result.success
    assert service.get(queued[0].draft.draft_id).draft.status is Status.SENT
    with pytest.raises(SendBlocked):
        service.send(queued[0].draft.draft_id)
    assert [a.state for a in service.store.attempts()] == ["SUCCEEDED"]


def test_no_duplicate_send_after_restart(tmp_path, two_contacts):
    first = make_service(tmp_path)
    d = first.create_drafts(two_contacts, TEMPLATE, "Team", "c").created[0]
    approve(first, d)
    first.send(d.draft.draft_id)
    second = make_service(tmp_path)
    with pytest.raises(SendBlocked):
        second.send(d.draft.draft_id)
    assert second.get(d.draft.draft_id).draft.status is Status.SENT


def test_sent_draft_cannot_be_edited_or_reopened(service, queued):
    approve(service, queued[0])
    service.send(queued[0].draft.draft_id)
    with pytest.raises(InvalidTransition):
        service.edit(queued[0].draft.draft_id, "Eve", body="late change")
    with pytest.raises(InvalidTransition):
        service.reopen(queued[0].draft.draft_id, "Eve")


def test_database_blocks_second_active_send_to_same_person(service, queued):
    approved = approve(service, queued[0])
    service.store.begin_send(approved.draft.draft_id, approved.version)
    from nucleate_outreach.store import SendInProgress
    with pytest.raises(SendInProgress):
        service.store.begin_send(approved.draft.draft_id, approved.version)


def test_simulated_failure_then_reopen_and_resend(service, queued):
    approve(service, queued[0])
    result = service.send(queued[0].draft.draft_id, fail_for={queued[0].draft.recipient})
    assert not result.success
    assert service.get(queued[0].draft.draft_id).draft.status is Status.FAILED
    service.reopen(queued[0].draft.draft_id, "Eve")
    service.submit_for_review(queued[0].draft.draft_id, "Eve")
    approve(service, service.get(queued[0].draft.draft_id))
    assert service.send(queued[0].draft.draft_id).success


def test_send_all_approved_skips_unapproved(service, queued):
    approve(service, queued[0])
    outcomes = service.send_all_approved("camp1")
    assert len(outcomes) == 1 and outcomes[0][1].success
    assert service.get(queued[1].draft.draft_id).draft.status is Status.PENDING_REVIEW


# ---------------------------------------------------------------- restart recovery
def test_crash_before_result_is_uncertain_and_blocks_resend(tmp_path, two_contacts):
    first = make_service(tmp_path)
    d = first.create_drafts(two_contacts, TEMPLATE, "Team", "c").created[0]
    approved = approve(first, d)
    first.store.begin_send(d.draft.draft_id, approved.version)  # ...program dies here
    second = make_service(tmp_path)  # restart runs recovery
    (att,) = second.uncertain_attempts()
    assert att.state == "UNCERTAIN"
    with pytest.raises(SendBlocked):
        second.send(d.draft.draft_id)
    with pytest.raises(DraftLocked):  # draft is frozen while the outcome is unknown
        second.edit(d.draft.draft_id, "Eve", body="x")


def test_uncertain_resolved_as_not_sent_allows_retry(tmp_path, two_contacts):
    first = make_service(tmp_path)
    d = first.create_drafts(two_contacts, TEMPLATE, "Team", "c").created[0]
    approve(first, d)
    first.store.begin_send(d.draft.draft_id, first.get(d.draft.draft_id).version)
    second = make_service(tmp_path)
    (att,) = second.uncertain_attempts()
    second.resolve_uncertain(att.attempt_id, False, "Rita", "checked the outbox")
    assert second.uncertain_attempts() == []
    assert second.send(d.draft.draft_id).success


def test_uncertain_resolved_as_sent_finalizes_and_blocks(tmp_path, two_contacts):
    first = make_service(tmp_path)
    d = first.create_drafts(two_contacts, TEMPLATE, "Team", "c").created[0]
    approve(first, d)
    first.store.begin_send(d.draft.draft_id, first.get(d.draft.draft_id).version)
    second = make_service(tmp_path)
    (att,) = second.uncertain_attempts()
    second.resolve_uncertain(att.attempt_id, True, "Rita")
    assert second.get(d.draft.draft_id).draft.status is Status.SENT
    with pytest.raises(SendBlocked):
        second.send(d.draft.draft_id)


def test_crash_after_delivery_is_recovered_from_ledger(tmp_path, two_contacts):
    first = make_service(tmp_path)
    d = first.create_drafts(two_contacts, TEMPLATE, "Team", "c").created[0]
    approved = approve(first, d)
    first.store.begin_send(d.draft.draft_id, approved.version)
    # delivery happened and the ledger was written, but the database result was not
    from nucleate_outreach.sender import SimulatedSender
    SimulatedSender(first._approvals, first._ledger_path).send(approved.draft)
    second = make_service(tmp_path)
    assert second.get(d.draft.draft_id).draft.status is Status.SENT
    assert second.uncertain_attempts() == []


def test_unexpected_error_during_send_leaves_uncertain(service, queued, monkeypatch):
    approve(service, queued[0])
    from nucleate_outreach import service as service_module

    def boom(self, draft):
        raise RuntimeError("network died")
    monkeypatch.setattr(service_module.SimulatedSender, "_deliver", boom)
    with pytest.raises(RuntimeError):
        service.send(queued[0].draft.draft_id)
    assert [a.state for a in service.store.attempts()] == ["UNCERTAIN"]
    with pytest.raises(SendBlocked):
        service.send(queued[0].draft.draft_id)
