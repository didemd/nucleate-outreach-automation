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


# ---- Milestone 2 fixtures ----
from nucleate_outreach.service import ReviewService  # noqa: E402
from nucleate_outreach.store import DraftStore  # noqa: E402

KEY = "test-key-0123456789-abcdef"


def make_service(tmp_path, key=KEY):
    """A service on a fresh database; call again with the same tmp_path to simulate a restart."""
    from nucleate_outreach.settings import Settings
    return ReviewService.from_settings(Settings(data_dir=tmp_path, approval_key=key))


@pytest.fixture
def service(tmp_path):
    return make_service(tmp_path)


@pytest.fixture
def two_contacts():
    return [
        Contact("Dr. Alice Example", "Fictional University", "alice@example.org", "protein engineering", True),
        Contact("Prof. Bob Sample", "Imaginary Institute", "bob@example.org", "quantum sensing", True),
    ]


@pytest.fixture
def queued(service, two_contacts):
    """Two PENDING_REVIEW drafts in campaign camp1."""
    return service.create_drafts(two_contacts, TEMPLATE, "Team", "camp1").created
