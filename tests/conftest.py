import pytest

from nucleate_outreach.approval import ApprovalService
from nucleate_outreach.contacts import Contact
from nucleate_outreach.drafts import create_draft
from nucleate_outreach.sender import SimulatedSender

TEMPLATE = "Subject: Hello {{first_name}}\nDear {{name}},\nYour work on {{research_area}} at {{institution}}.\n{{sender_name}}\n"


@pytest.fixture
def contact():
    return Contact("Dr. Alice Example", "Fictional University", "alice@example.org", "protein engineering", True)


@pytest.fixture
def approvals():
    return ApprovalService("test-key-0123456789-abcdef")


@pytest.fixture
def sender(approvals, tmp_path):
    return SimulatedSender(approvals, tmp_path / "ledger.jsonl")


@pytest.fixture
def draft(contact):
    return create_draft(contact, TEMPLATE, "Team", "camp1")


@pytest.fixture
def pending(draft):
    draft.submit_for_review()
    return draft


@pytest.fixture
def approved(pending, approvals):
    approvals.approve(pending, "Reviewer")
    return pending
