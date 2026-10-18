from pathlib import Path

import pytest

from nucleate_outreach.contacts import load_contacts_csv

FIXTURE = Path(__file__).parent / "fixtures" / "contacts.csv"


def test_valid_contacts_loaded_and_emails_lowercased():
    result = load_contacts_csv(FIXTURE)
    assert [c.email for c in result.contacts] == ["alice@example.org", "bob@example.org", "alice2@example.org"]


def test_invalid_rows_reported_not_loaded():
    result = load_contacts_csv(FIXTURE)
    messages = " | ".join(i.message for i in result.invalid)
    assert "invalid email" in messages
    assert "missing value for: name" in messages
    assert "yes/no" in messages
    assert len(result.invalid) == 3


def test_duplicate_email_detected_case_insensitively():
    result = load_contacts_csv(FIXTURE)
    assert len(result.duplicates) == 1
    assert "alice@example.org" in result.duplicates[0].message
    assert sum(c.email == "alice@example.org" for c in result.contacts) == 1


def test_same_person_different_email_warns():
    result = load_contacts_csv(FIXTURE)
    assert len(result.warnings) == 1


def test_eligibility_parsed():
    result = load_contacts_csv(FIXTURE)
    assert {c.email for c in result.eligible} == {"alice@example.org", "alice2@example.org"}


def test_missing_column_raises(tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text("name,email\nA,a@example.org\n")
    with pytest.raises(ValueError, match="missing required column"):
        load_contacts_csv(bad)
