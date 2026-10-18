"""Template library, complete-draft import, provenance and the pure dashboard helpers."""

import io
import sqlite3

import pytest

from nucleate_outreach.draft_import import example_csv, example_xlsx, plan_import, read_table
from nucleate_outreach.drafts import Status, fingerprint
from nucleate_outreach.sender_identity import NOT_CONNECTED_TEXT, current_sender_identity
from nucleate_outreach.store import DraftStore
from nucleate_outreach.template_library import (TemplateLibrary, decode_upload, validate_template_text,
                                                variables_in)
from nucleate_outreach.templating import TemplateError

from conftest import TEMPLATE, make_service

GOOD = "Subject: Hello {{first_name}}\nDear {{name}}, about {{research_area}} at {{institution}}.\n{{sender_name}}\n"
HEADER = "campaign,contact_id,recipient_email,recipient_name,subject,body,personalization_notes\n"


def csv_bytes(*rows, header=HEADER):
    return (header + "".join(rows)).encode("utf-8")


def none_exist(campaign, email):
    return False


# ------------------------------------------------------------------ template library
def test_templates_are_versioned_never_overwritten(tmp_path):
    lib = TemplateLibrary(tmp_path / "t.db")
    v1 = lib.create("Intro", GOOD)
    v2 = lib.save_new_version(v1.template_id, GOOD + "P.S. new\n", "added a postscript")
    assert (v1.version, v2.version) == (1, 2)
    assert lib.get(v1.template_id, 1).content == GOOD  # old version intact
    assert lib.get(v1.template_id).version == 2         # default = latest
    assert [v.version for v in lib.versions(v1.template_id)] == [2, 1]


def test_template_names_are_unique_case_insensitively(tmp_path):
    lib = TemplateLibrary(tmp_path / "t.db")
    lib.create("Intro", GOOD)
    with pytest.raises(TemplateError):
        lib.create("intro", GOOD)


@pytest.mark.parametrize("text, fragment", [
    ("Hello there\nbody", "Subject:"),
    ("Subject: Hi\n", "no body"),
    ("Subject:\nbody text", "empty"),
    ("Subject: Hi {{favourite_colour}}\nbody", "Unknown variable"),
    ("Subject: Hi\nbody\x00", "binary"),
    ("Subject: Hi\n" + "x" * 60_000, "longer"),
])
def test_template_validation_catches_problems(text, fragment):
    assert any(fragment in p for p in validate_template_text(text))


def test_valid_template_has_no_problems_and_lists_variables():
    assert validate_template_text(GOOD) == []
    assert variables_in(GOOD) == ["first_name", "name", "research_area", "institution", "sender_name"]


def test_upload_decoding_rules():
    assert decode_upload("a.md", "Subject: x\r\nbody ünï".encode("utf-8")) == "Subject: x\nbody ünï"
    with pytest.raises(TemplateError):
        decode_upload("a.exe", b"Subject: x")
    with pytest.raises(TemplateError):
        decode_upload("a.txt", b"\xff\xfe\x00bad")
    with pytest.raises(TemplateError):
        decode_upload("a.txt", b"x" * 60_000)


def test_invalid_template_cannot_be_saved(tmp_path):
    lib = TemplateLibrary(tmp_path / "t.db")
    with pytest.raises(TemplateError):
        lib.create("Bad", "no subject line")
    assert lib.list() == []


def test_examples_are_seeded_once_and_bad_examples_are_skipped(tmp_path):
    folder = tmp_path / "examples"
    folder.mkdir()
    (folder / "good_one.txt").write_text(GOOD, encoding="utf-8")
    (folder / "broken.txt").write_text("nonsense", encoding="utf-8")
    (folder / "ignored.csv").write_text("a,b", encoding="utf-8")
    lib = TemplateLibrary(tmp_path / "t.db")
    lib.seed_examples(folder)
    lib.seed_examples(folder)
    assert [t.name for t in lib.list()] == ["Good one (example)"]
    assert lib.list()[0].is_example and lib.list()[0].latest_version == 1


def test_repository_example_templates_are_valid():
    from nucleate_outreach.settings import ROOT
    for file in (ROOT / "templates").glob("*"):
        if file.suffix in (".txt", ".md"):
            assert validate_template_text(decode_upload(file.name, file.read_bytes())) == [], file.name


def test_service_seeds_example_templates(service):
    assert any(t.is_example for t in service.templates.list())


# ------------------------------------------------------------------ provenance
def test_drafts_remember_the_template_version_they_came_from(service, two_contacts):
    v1 = service.templates.create("Intro", TEMPLATE)
    v2 = service.templates.save_new_version(v1.template_id, TEMPLATE + "PS\n")
    report = service.create_drafts(two_contacts, v2.content, "Team", "c1", template=v2)
    meta = service.draft_meta(report.created[0].draft.draft_id)
    assert (meta.source_kind, meta.template_name, meta.template_version) == ("template", "Intro", 2)
    assert "PS" in report.created[0].draft.body


def test_drafts_without_a_template_have_no_meta(queued, service):
    assert service.draft_meta(queued[0].draft.draft_id) is None


def test_old_database_without_meta_table_still_opens(tmp_path, two_contacts):
    service = make_service(tmp_path)
    created = service.create_drafts(two_contacts, TEMPLATE, "Team", "c1").created
    with sqlite3.connect(tmp_path / "outreach.db") as conn:
        conn.execute("DROP TABLE draft_meta")
    reopened = make_service(tmp_path)
    assert reopened.get(created[0].draft.draft_id).draft.status is Status.PENDING_REVIEW
    assert reopened.draft_meta(created[0].draft.draft_id) is None


# ------------------------------------------------------------------ draft import: parsing
def test_import_keeps_subject_and_body_exactly():
    body = "  Liebe Frau Müller,\r\n\r\n  zwei Zeilen\nund ein Emoji 🙂\n\n  Grüße  \n"
    row = '"c1","K1","a@example.org","A","  Betreff – Übung  ","' + body.replace('"', '""') + '","note"\n'
    plan = plan_import("x.csv", csv_bytes(row), none_exist)
    assert not plan.errors
    got = plan.ready[0]
    assert got.body == body and got.subject == "  Betreff – Übung  "
    assert (got.contact_id, got.recipient_name, got.notes) == ("K1", "A", "note")


def test_import_creates_normal_pending_drafts_with_exact_text(service):
    body = "Zeile 1\n\nZeile 3 – ünï 🙂 \n"
    plan = plan_import("x.csv", csv_bytes(f'c1,K9,A@Example.org,A,"Hi, there","{body}",n\n'), none_exist)
    report = service.import_drafts(plan.ready, "op", "x.csv")
    stored = report.created[0]
    assert stored.draft.status is Status.PENDING_REVIEW and stored.draft.approval is None
    assert stored.draft.body == body and stored.draft.subject == "Hi, there"
    assert stored.draft.fingerprint == fingerprint("a@example.org", "Hi, there", body)
    meta = service.draft_meta(stored.draft.draft_id)
    assert (meta.source_kind, meta.source_file, meta.contact_id, meta.notes) == ("imported", "x.csv", "K9", "n")


def test_file_cannot_supply_status_or_approval(service):
    header = HEADER.strip() + ",status,approval_signature,approved_by,fingerprint\n"
    plan = plan_import("x.csv", csv_bytes("c1,K1,a@example.org,A,S,B,n,APPROVED,deadbeef,Eve,abc\n", header=header),
                       none_exist)
    assert plan.file_warnings and "status" in plan.file_warnings[0]
    stored = service.import_drafts(plan.ready, "op", "x.csv").created[0]
    assert stored.draft.status is Status.PENDING_REVIEW and stored.draft.approval is None
    assert service.approval_is_valid(stored) is None
    with pytest.raises(Exception):  # cannot be sent: it is not approved
        service.send(stored.draft.draft_id)


def test_import_validation_errors_are_reported_per_row():
    rows = ("c1,1,not-an-email,A,S,B,\n"
            "c1,2,b@example.org,B,,B,\n"
            'c1,3,c@example.org,C,"two\nlines",B,\n'
            "c1,4,d@example.org,D,S,   ,\n"
            ",5,e@example.org,E,S,B,\n"
            "c1,6,ok@example.org,F,S,B,\n")
    plan = plan_import("x.csv", csv_bytes(rows), none_exist)
    assert [r.row for r in plan.ready] == [7]
    assert {e.row for e in plan.errors} == {2, 3, 4, 5, 6}
    messages = " ".join(e.message for e in plan.errors)
    for needle in ("invalid recipient", "subject is empty", "single line", "body is empty", "no campaign"):
        assert needle in messages


def test_default_campaign_fills_blank_campaign_cells():
    plan = plan_import("x.csv", csv_bytes(",1,a@example.org,A,S,B,\n"), none_exist, default_campaign="fallback")
    assert plan.ready[0].campaign == "fallback"


def test_duplicates_inside_the_file_are_rejected():
    rows = "c1,1,a@example.org,A,S,B,\nc1,2,A@EXAMPLE.org,A2,S2,B2,\nc2,3,a@example.org,A,S,B,\n"
    plan = plan_import("x.csv", csv_bytes(rows), none_exist)
    assert [r.row for r in plan.ready] == [2, 4]  # same person in a different campaign is fine
    assert "duplicate of row 2" in plan.errors[0].message


def test_importing_the_same_file_twice_creates_nothing_new(service):
    data = csv_bytes("c1,1,a@example.org,A,S,B,\nc1,2,b@example.org,B,S,B,\n")
    first = plan_import("x.csv", data, service.draft_exists)
    assert len(service.import_drafts(first.ready, "op", "x.csv").created) == 2
    second = plan_import("x.csv", data, service.draft_exists)
    assert second.ready == [] and len(second.already_exists) == 2
    # even if the preview were skipped, the database refuses the duplicates
    report = service.import_drafts(first.ready, "op", "x.csv")
    assert report.created == [] and len(report.skipped_existing) == 2
    assert len(service.list_drafts("c1")) == 2


def test_import_also_collides_with_template_generated_drafts(service, two_contacts):
    service.create_drafts(two_contacts, TEMPLATE, "Team", "camp1")
    plan = plan_import("x.csv", csv_bytes("camp1,1,alice@example.org,A,S,B,\n"), service.draft_exists)
    assert plan.ready == [] and len(plan.already_exists) == 1


@pytest.mark.parametrize("data, fragment", [
    (b"", "empty"),
    (HEADER.encode(), "no emails"),
    (b"campaign,subject\nc,s\n", "missing required column"),
    (b"\xff\xfe\x00\x00", "UTF-8"),
])
def test_bad_files_give_friendly_errors(data, fragment):
    with pytest.raises(ValueError, match=fragment):
        plan_import("x.csv", data, none_exist)


def test_wrong_file_type_and_oversize_are_refused():
    with pytest.raises(ValueError, match=".csv or .xlsx"):
        read_table("x.pdf", b"%PDF")
    with pytest.raises(ValueError, match="larger"):
        read_table("x.csv", b"x" * 5_000_001)
    with pytest.raises(ValueError, match="valid .xlsx"):
        read_table("x.xlsx", b"this is not a zip file")


def test_ambiguous_columns_are_refused():
    header = "campaign,email,recipient_email,subject,body\n"
    with pytest.raises(ValueError, match="Several columns"):
        plan_import("x.csv", csv_bytes("c,a@example.org,a@example.org,S,B\n", header=header), none_exist)


def test_downloadable_examples_pass_their_own_validation():
    for name, data in (("example.csv", example_csv()), ("example.xlsx", example_xlsx())):
        plan = plan_import(name, data, none_exist)
        assert len(plan.ready) == 2 and not plan.errors and not plan.file_warnings
        assert "Gründung" in plan.ready[1].subject and "\n" in plan.ready[0].body  # Unicode + multiline survive


def test_xlsx_import_preserves_multiline_text_and_numbers():
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.append(["campaign", "contact_id", "recipient_email", "subject", "body"])
    ws.append(["c1", 1001, "a@example.org", "Grüße", "line one\nline two ✓"])
    buffer = io.BytesIO()
    wb.save(buffer)
    plan = plan_import("x.xlsx", buffer.getvalue(), none_exist)
    assert plan.ready[0].contact_id == "1001" and plan.ready[0].body == "line one\nline two ✓"


# ------------------------------------------------------------------ approval workflow on imported drafts
def test_imported_draft_goes_through_normal_approval_and_edit_invalidation(service):
    plan = plan_import("x.csv", csv_bytes("c1,1,a@example.org,A,Subj,Body text,\n"), none_exist)
    stored = service.import_drafts(plan.ready, "op", "x.csv").created[0]
    approved = service.approve(stored.draft.draft_id, "op", stored.draft.fingerprint)
    assert approved.draft.status is Status.APPROVED
    edited = service.edit(stored.draft.draft_id, "op", body="Body text!")
    assert edited.draft.status is Status.DRAFT and edited.draft.approval is None
    assert service.draft_meta(stored.draft.draft_id).source_kind == "imported"  # provenance survives edits


# ------------------------------------------------------------------ campaign numbers & helpers
def test_campaign_metrics_use_plain_numbers(service, two_contacts):
    from nucleate_outreach.dashboard.view import metrics_for
    created = service.create_drafts(two_contacts, TEMPLATE, "Team", "c1").created
    service.approve(created[0].draft.draft_id, "op", created[0].draft.fingerprint)
    service.reject(created[1].draft.draft_id, "op", "no")
    m = metrics_for(service.campaign_progress("c1")["c1"], uncertain=2)
    assert m == {"Total drafts": 2, "Pending review": 0, "Approved": 1, "Rejected": 1,
                 "Simulated sent": 0, "Failed or uncertain": 2}


def test_friendly_status_labels_cover_every_status():
    from nucleate_outreach.dashboard.view import STATUS_LABEL, status_label
    assert set(STATUS_LABEL) == set(Status)
    assert status_label(Status.PENDING_REVIEW) == "Pending review"
    assert "_" not in "".join(STATUS_LABEL.values())


def test_row_selection_logic(queued):
    from nucleate_outreach.dashboard.view import resolve_selection
    a, b = queued[0].draft.draft_id, queued[1].draft.draft_id
    assert resolve_selection(queued, [1], None, None) == (b, b)          # a click opens that row
    assert resolve_selection(queued, [], b, b) == (b, None)              # table redrew: stay on the open email
    assert resolve_selection(queued, [0], b, b) == (a, a)                # a different click switches
    assert resolve_selection(queued, [0], a, a) == (a, a)                # same click again: unchanged
    assert resolve_selection(queued, [7], a, a) == (a, None)             # out-of-range click is ignored


def test_sender_identity_is_not_connected_by_default():
    ident = current_sender_identity()
    assert ident.headline == NOT_CONNECTED_TEXT == "Not connected — simulated sending only."
    assert ident.email is None and not ident.connected and ident.last_verified_at is None


# ------------------------------------------------------------------ create-in-dashboard helper
def test_compose_template_builds_the_stored_format():
    from nucleate_outreach.template_library import compose_template
    text = compose_template("  Hallo {{first_name}}  ", "Liebe {{name}},\r\n\r\nGrüße 🙂\n\n")
    assert text == "Subject: Hallo {{first_name}}\nLiebe {{name}},\n\nGrüße 🙂\n"
    assert validate_template_text(text) == []


@pytest.mark.parametrize("subject, body, fragment", [
    ("", "body", "subject"),
    ("   ", "body", "subject"),
    ("two\nlines", "body", "single line"),
    ("x" * 201, "body", "longer"),
    ("Hi", "  \n ", "email text"),
])
def test_compose_template_rejects_invalid_input(subject, body, fragment):
    from nucleate_outreach.template_library import compose_template
    with pytest.raises(TemplateError, match=fragment):
        compose_template(subject, body)


# ------------------------------------------------------------------ templates + approval/sending safeguards
def test_template_made_drafts_obey_every_approval_and_sending_safeguard(service, two_contacts):
    from nucleate_outreach.sender import SendBlocked
    from nucleate_outreach.template_library import compose_template
    tpl = service.templates.create("Pasted", compose_template("Hi {{first_name}}", "Dear {{name}},\n{{sender_name}}"))
    drafts = service.create_drafts(two_contacts, tpl.content, "Team", "c1", template=tpl).created
    d = drafts[0].draft
    assert d.status is Status.PENDING_REVIEW and d.approval is None
    with pytest.raises(SendBlocked):                      # unapproved: cannot be sent
        service.send(d.draft_id)
    ok = service.approve(d.draft_id, "op", d.fingerprint)
    assert service.approval_is_valid(ok) is True
    # a new template version never changes drafts that already exist
    service.templates.save_new_version(tpl.template_id, tpl.content + "PS\n")
    assert service.get(d.draft_id).draft.body == d.body and service.approval_is_valid(service.get(d.draft_id)) is True
    # any edit cancels the approval and blocks sending again
    service.edit(d.draft_id, "op", body=d.body + " changed")
    with pytest.raises(SendBlocked):
        service.send(d.draft_id)
    again = service.get(d.draft_id)
    service.submit_for_review(d.draft_id, "op")
    service.approve(d.draft_id, "op", service.get(d.draft_id).draft.fingerprint)
    assert service.send(d.draft_id).success                # approved + unchanged: simulated send works
    with pytest.raises(SendBlocked):                       # and only once
        service.send(d.draft_id)
    assert again.draft.approval is None
    assert service.get(drafts[1].draft.draft_id).draft.status is Status.PENDING_REVIEW  # others untouched
