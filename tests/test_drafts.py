import pytest

from nucleate_outreach.contacts import Contact
from nucleate_outreach.drafts import create_draft
from nucleate_outreach.templating import TemplateError, render_email
from conftest import TEMPLATE


def test_draft_is_personalized(draft):
    assert draft.subject == "Hello Alice"
    assert "Dear Dr. Alice Example," in draft.body
    assert "protein engineering" in draft.body and "Fictional University" in draft.body
    assert "{{" not in draft.body
    assert draft.recipient == "alice@example.org"


def test_generation_is_deterministic(contact):
    assert render_email(TEMPLATE, contact, "Team") == render_email(TEMPLATE, contact, "Team")


def test_unknown_placeholder_fails(contact):
    with pytest.raises(TemplateError):
        render_email("Subject: Hi\nHello {{nonexistent}}", contact, "Team")


def test_template_needs_subject(contact):
    with pytest.raises(TemplateError):
        render_email("No subject line\nbody", contact, "Team")


def test_ineligible_contact_refused():
    c = Contact("Bob", "Inst", "bob@example.org", "area", False)
    with pytest.raises(ValueError, match="not eligible"):
        create_draft(c, TEMPLATE, "Team", "camp1")


def test_newline_in_subject_rejected(contact):
    with pytest.raises(ValueError):
        render_email("Subject: {{name}}\nbody", Contact("A\nBcc: x@evil.test", "I", "a@example.org", "r", True), "T")
