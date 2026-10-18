"""Safe local demonstration: fictional contacts, simulated sending only.

Run:  python -m nucleate_outreach.demo
"""

from __future__ import annotations

import json
import os
import secrets
import tempfile
from pathlib import Path

from .approval import ApprovalService
from .contacts import load_contacts_csv
from .drafts import create_draft
from .sender import SendBlocked, SimulatedSender
from .templating import load_template

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    print("=== Nucleate outreach demo (SIMULATION - nothing is sent) ===\n")
    config = json.loads((ROOT / "config" / "campaign.example.json").read_text(encoding="utf-8"))

    result = load_contacts_csv(ROOT / "examples" / "example_contacts.csv")
    print(f"Loaded {len(result.contacts)} valid contacts ({len(result.eligible)} eligible)")
    for issue in result.invalid:
        print(f"  invalid  row {issue.row}: {issue.message}")
    for issue in result.duplicates:
        print(f"  duplicate row {issue.row}: {issue.message}")

    template = load_template(ROOT / config["template_file"])
    drafts = [create_draft(c, template, config["sender_name"], config["campaign_id"]) for c in result.eligible]
    print(f"\nCreated {len(drafts)} drafts. Showing the first:\n")
    first = drafts[0]
    print(f"To: {first.recipient}\nSubject: {first.subject}\n\n{first.body}\n")

    key = os.environ.get("OUTREACH_APPROVAL_KEY") or secrets.token_hex(32)
    approvals = ApprovalService(key)
    # The demo uses a throwaway ledger so it never touches real records.
    ledger = Path(tempfile.mkdtemp()) / "demo_ledger.jsonl"
    sender = SimulatedSender(approvals, ledger, fail_for={"dan@example.org"})

    for draft in drafts:
        draft.submit_for_review()

    print("1) Trying to send an UNAPPROVED draft:")
    try:
        sender.send(first)
    except SendBlocked as exc:
        print(f"   {exc}")

    approvals.approve(drafts[0], reviewer="Demo Reviewer")
    approvals.approve(drafts[1], reviewer="Demo Reviewer")
    approvals.approve(drafts[2], reviewer="Demo Reviewer")

    print("\n2) Editing an approved draft invalidates the approval:")
    drafts[1].edit(body=drafts[1].body + "\nP.S. Added after approval.")
    print(f"   status is now {drafts[1].status.value}")
    try:
        sender.send(drafts[1])
    except SendBlocked as exc:
        print(f"   {exc}")

    print("\n3) Sending approved drafts (simulated):")
    for draft in (drafts[0], drafts[2]):
        outcome = sender.send(draft)
        print(f"   {outcome.recipient}: {draft.status.value} - {outcome.detail}")

    print("\n4) Sending the same draft twice:")
    try:
        sender.send(drafts[0])
    except SendBlocked as exc:
        print(f"   {exc}")

    print(f"\nSimulated ledger (temporary file): {ledger}")


if __name__ == "__main__":
    main()
