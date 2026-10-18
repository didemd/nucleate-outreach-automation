"""ReviewService: the single backend entry point used by the dashboard.

The UI never touches the database or changes a Draft directly. Every action
goes through a method here, and each method re-loads the draft from the
database and re-checks the rules, so a stale page or a hand-crafted request
cannot skip a rule. The approval and sending checks themselves are the
Milestone 1 classes (ApprovalService, Sender), reused unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass

from .approval import ApprovalError, ApprovalService
from .contacts import Contact, is_valid_email
from .drafts import Draft, InvalidTransition, Status, create_draft
from .sender import SendBlocked, SendResult, SimulatedSender
from .settings import ROOT, Settings
from .draft_import import DraftRow
from .store import (ConcurrentModification, DraftMeta, DraftStore, DuplicateDraft, Event, SendAttempt,
                    SendInProgress, StoredDraft)
from .template_library import TemplateLibrary, TemplateVersion


class PermissionDenied(Exception):
    """The action needs the approval key, which is not configured (read-only mode)."""


@dataclass
class ImportReport:
    created: list[StoredDraft]
    skipped_existing: list[str]  # recipients that already had a draft in this campaign


class ReviewService:
    def __init__(self, store: DraftStore, approvals: ApprovalService | None, ledger_path,
                 templates: TemplateLibrary | None = None) -> None:
        self.store = store
        self._approvals = approvals
        self._ledger_path = ledger_path
        self.templates = templates or TemplateLibrary(store.path)

    @classmethod
    def from_settings(cls, settings: Settings) -> "ReviewService":
        approvals = None
        if settings.approval_key:
            try:
                approvals = ApprovalService(settings.approval_key)
            except ApprovalError:
                approvals = None  # invalid/placeholder key -> read-only (fail closed)
        service = cls(DraftStore(settings.db_path), approvals, settings.ledger_path)
        service.templates.seed_examples(ROOT / "templates")
        service.recover_interrupted()
        return service

    @property
    def can_approve(self) -> bool:
        return self._approvals is not None

    def _require_approvals(self) -> ApprovalService:
        if self._approvals is None:
            raise PermissionDenied(
                "No valid OUTREACH_APPROVAL_KEY is configured, so approving and sending are disabled."
            )
        return self._approvals

    @staticmethod
    def _require_name(name: str, what: str = "reviewer") -> str:
        if not name or not name.strip():
            raise ValueError(f"A {what} name is required")
        return name.strip()

    # ---- creating drafts -----------------------------------------------------
    def create_drafts(self, contacts: list[Contact], template_text: str, sender_name: str,
                      campaign_id: str, actor: str = "system",
                      template: TemplateVersion | None = None) -> ImportReport:
        """Make one draft per eligible contact and put it in the review queue.

        If `template` (a library version) is given, each draft remembers which
        template version it was generated from.
        """
        campaign_id = self._require_name(campaign_id, "campaign")
        created, skipped = [], []
        for contact in contacts:
            if not contact.outreach_eligible:
                continue
            draft = create_draft(contact, template_text, sender_name, campaign_id)
            meta = DraftMeta("template", template.template_id, template.name, template.version,
                             contact_id=None, recipient_name=contact.name) if template else None
            try:
                stored = self.store.add(draft, actor, meta)
            except DuplicateDraft:
                skipped.append(contact.email)
                continue
            draft = stored.draft
            draft.submit_for_review()
            created.append(self.store.save(draft, stored.version, actor))
        return ImportReport(created, skipped)

    def import_drafts(self, rows: list[DraftRow], actor: str, source_file: str) -> ImportReport:
        """Put complete, externally written emails into the normal review queue.

        Content is stored exactly as given. Status and approval always start
        fresh (Draft -> Pending review); nothing about approval comes from the file.
        """
        actor = self._require_name(actor, "importer")
        created, skipped = [], []
        for row in rows:
            draft = Draft(recipient=row.recipient_email, subject=row.subject, body=row.body,
                          campaign_id=row.campaign)
            meta = DraftMeta("imported", source_file=source_file, contact_id=row.contact_id or None,
                             recipient_name=row.recipient_name or None, notes=row.notes or None)
            try:
                stored = self.store.add(draft, actor, meta)
            except DuplicateDraft:
                skipped.append(row.recipient_email)
                continue
            draft = stored.draft
            draft.submit_for_review()
            created.append(self.store.save(draft, stored.version, actor))
        return ImportReport(created, skipped)

    def draft_meta(self, draft_id: str) -> DraftMeta | None:
        return self.store.get_meta(draft_id)

    def draft_exists(self, campaign_id: str, recipient: str) -> bool:
        return self.store.exists(campaign_id, recipient)

    # ---- reading -------------------------------------------------------------
    def list_drafts(self, campaign_id=None, statuses=None) -> list[StoredDraft]:
        return self.store.list(campaign_id, statuses)

    def get(self, draft_id: str) -> StoredDraft:
        return self.store.get(draft_id)

    def events(self, draft_id: str) -> list[Event]:
        return self.store.events(draft_id)

    def decisions(self, draft_id: str) -> list[Event]:
        kinds = {"APPROVED", "REJECTED", "APPROVAL_INVALIDATED"}
        return [e for e in self.store.events(draft_id) if e.kind in kinds]

    def approval_is_valid(self, stored: StoredDraft) -> bool | None:
        """True/False if the stored approval verifies against the CURRENT content; None if unknowable (no key)."""
        if stored.draft.status is not Status.APPROVED:
            return None
        if self._approvals is None:
            return None
        try:
            self._approvals.verify(stored.draft)
            return True
        except ApprovalError:
            return False

    def campaign_progress(self, campaign_id: str | None = None) -> dict[str, dict[str, int]]:
        return self.store.status_counts(campaign_id)

    # ---- editing -------------------------------------------------------------
    def edit(self, draft_id: str, actor: str, *, recipient: str | None = None,
             subject: str | None = None, body: str | None = None) -> StoredDraft:
        """Change content. Any real change discards the approval (Draft.edit does that)."""
        actor = self._require_name(actor, "editor")
        stored = self.store.get(draft_id)
        draft = stored.draft
        if recipient is not None and not is_valid_email(recipient.strip()):
            raise ValueError(f"Invalid email address: {recipient!r}")
        changed = [
            name for name, new, old in (("recipient", recipient, draft.recipient),
                                        ("subject", subject, draft.subject),
                                        ("body", body, draft.body))
            if new is not None and new != old
        ]
        if not changed:
            return stored  # nothing changed -> keep any existing approval
        previous = draft.approval
        draft.edit(recipient=recipient, subject=subject, body=body)  # may raise InvalidTransition (SENT)
        events = [("EDITED", "changed: " + ", ".join(changed))]
        if previous is not None:
            events.append(("APPROVAL_INVALIDATED", f"edit by {actor} removed approval by {previous.reviewer}"))
        return self.store.save(draft, stored.version, actor, events)

    def reopen(self, draft_id: str, actor: str) -> StoredDraft:
        """Move a REJECTED or FAILED draft back to DRAFT so it can be revised."""
        actor = self._require_name(actor, "editor")
        stored = self.store.get(draft_id)
        if stored.draft.status not in (Status.REJECTED, Status.FAILED):
            raise InvalidTransition("Only rejected or failed drafts can be reopened")
        stored.draft.edit()
        return self.store.save(stored.draft, stored.version, actor)

    def submit_for_review(self, draft_id: str, actor: str) -> StoredDraft:
        actor = self._require_name(actor, "editor")
        stored = self.store.get(draft_id)
        stored.draft.submit_for_review()
        return self.store.save(stored.draft, stored.version, actor)

    # ---- approval ------------------------------------------------------------
    def approve(self, draft_id: str, reviewer: str, seen_fingerprint: str) -> StoredDraft:
        """Approve a draft, but only if it still has the content the reviewer was looking at."""
        approvals = self._require_approvals()
        reviewer = self._require_name(reviewer)
        stored = self.store.get(draft_id)
        draft = stored.draft
        if draft.fingerprint != seen_fingerprint:
            raise ConcurrentModification("The email changed after you opened it; review the new version")
        approvals.approve(draft, reviewer)  # Milestone 1 logic: state check + signature
        return self.store.save(draft, stored.version, reviewer, [("APPROVED", f"approved by {reviewer}")])

    def reject(self, draft_id: str, reviewer: str, reason: str = "") -> StoredDraft:
        reviewer = self._require_name(reviewer)
        stored = self.store.get(draft_id)
        draft = stored.draft
        if self._approvals is not None:
            self._approvals.reject(draft, reviewer, reason)
        else:  # rejecting is always safe, so it is allowed even without a key
            if draft.status is not Status.PENDING_REVIEW:
                raise InvalidTransition(f"Only PENDING_REVIEW drafts can be rejected (status is {draft.status.value})")
            draft.approval = None
            draft.transition(Status.REJECTED)
        return self.store.save(draft, stored.version, reviewer,
                               [("REJECTED", f"rejected by {reviewer}: {reason or 'no reason given'}")])

    # ---- simulated sending ---------------------------------------------------
    def send(self, draft_id: str, fail_for: set[str] | None = None) -> SendResult:
        """Send one approved draft (SIMULATED).

        Order of events, chosen so every crash point is safe:
          1. verify the approval (fail closed)
          2. durably record SEND_STARTED (unique index blocks a second send)
          3. run the Milestone 1 sender (re-verifies, checks ledger, "delivers")
          4. durably record the result
        """
        approvals = self._require_approvals()
        stored = self.store.get(draft_id)
        draft = stored.draft
        try:
            approvals.verify(draft)
        except ApprovalError as exc:
            raise SendBlocked(f"Blocked: {exc}") from exc
        try:
            attempt_id = self.store.begin_send(draft_id, stored.version)
        except SendInProgress as exc:
            raise SendBlocked(f"Blocked: {exc}") from exc
        except ConcurrentModification as exc:
            raise SendBlocked(f"Blocked: {exc}") from exc

        sender = SimulatedSender(approvals, self._ledger_path, fail_for=fail_for)
        try:
            result = sender.send(draft)
        except SendBlocked as exc:  # refused before delivery -> nothing was sent
            self.store.abort_send(attempt_id, str(exc))
            raise
        except BaseException as exc:
            # We cannot know whether delivery happened. Keep the lock (UNCERTAIN) for a human to resolve.
            self.store.mark_uncertain(attempt_id, f"unexpected error during send: {exc!r}")
            raise
        self.store.finish_send(attempt_id, result.success, result.detail)
        return result

    def send_all_approved(self, campaign_id: str | None = None, fail_for: set[str] | None = None):
        """Try every APPROVED draft. Returns a list of (draft_id, SendResult | error message)."""
        outcomes = []
        for stored in self.store.list(campaign_id, [Status.APPROVED]):
            try:
                outcomes.append((stored.draft.draft_id, self.send(stored.draft.draft_id, fail_for)))
            except (SendBlocked, PermissionDenied) as exc:
                outcomes.append((stored.draft.draft_id, str(exc)))
        return outcomes

    # ---- recovery ------------------------------------------------------------
    def recover_interrupted(self) -> list[SendAttempt]:
        """Run at start-up. Any attempt still STARTED means the program stopped mid-send.

        * ledger shows a successful delivery -> finish it as sent
        * otherwise -> UNCERTAIN: duplicates stay blocked until a human decides
        """
        handled = []
        stale = self.store.attempts(states=("STARTED",))
        if not stale:
            return handled
        checker = SimulatedSender(self._approvals or _NoApprovals(), self._ledger_path)
        for att in stale:
            if checker.has_success_record(att.draft_id):
                self.store.finish_send(att.attempt_id, True, "recovered after restart: ledger shows delivery")
            else:
                self.store.mark_uncertain(att.attempt_id, "interrupted before the result was recorded")
            handled.append(att)
        return handled

    def uncertain_attempts(self) -> list[SendAttempt]:
        return self.store.attempts(states=("UNCERTAIN",))

    def resolve_uncertain(self, attempt_id: str, actually_sent: bool, reviewer: str, note: str = "") -> None:
        reviewer = self._require_name(reviewer)
        self.store.resolve_attempt(attempt_id, actually_sent, reviewer, note)


class _NoApprovals:
    """Placeholder so ledger inspection works in read-only mode; it can never verify anything."""

    def verify(self, draft: Draft) -> None:
        raise ApprovalError("No approval key configured")
