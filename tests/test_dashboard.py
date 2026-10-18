"""Drives the real Streamlit script headlessly (five-tab layout) and checks the backend state afterwards."""

from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402
import streamlit as st  # noqa: E402

from nucleate_outreach.draft_import import example_csv, example_xlsx  # noqa: E402
from nucleate_outreach.drafts import Status  # noqa: E402
from nucleate_outreach.settings import LOCAL_OPERATOR  # noqa: E402
from conftest import KEY, TEMPLATE, make_service  # noqa: E402

APP = Path(__file__).parents[1] / "src" / "nucleate_outreach" / "dashboard" / "app.py"
SELECTED = "selected_draft"


@pytest.fixture
def app_env(tmp_path, monkeypatch, two_contacts):
    monkeypatch.setenv("OUTREACH_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OUTREACH_APPROVAL_KEY", KEY)
    st.cache_resource.clear()  # the app caches its service; start clean for each test
    service = make_service(tmp_path)
    created = service.create_drafts(two_contacts, TEMPLATE, "Team", "camp1").created
    yield service, created
    st.cache_resource.clear()


def start(open_draft=None):
    """Load the app; optionally open one email as if its table row had been clicked."""
    at = AppTest.from_file(str(APP), default_timeout=30)
    if open_draft is not None:
        at.session_state[SELECTED] = open_draft.draft.draft_id
    at.run()
    assert not at.exception
    return at


def button(at, text):
    return next(b for b in at.button if text in b.label)


def texts(at):
    parts = [*at.markdown, *at.caption, *at.subheader, *at.success, *at.warning, *at.info]
    return " ".join(p.value for p in parts)


# ------------------------------------------------------------------ layout
def test_five_named_tabs_and_no_sidebar_navigation(app_env):
    at = start()
    assert [t.label for t in at.tabs] == ["Emails", "Import", "Templates", "Campaigns", "Settings"]
    assert len(at.sidebar) == 0 or not at.sidebar.radio


def test_no_reviewer_name_input_anywhere(app_env):
    at = start()
    assert not any("reviewer" in (t.label or "").lower() for t in at.text_input)


def test_sender_banner_says_not_connected_and_has_no_address_input(app_env):
    at = start()
    assert "Not connected — simulated sending only." in texts(at)
    assert not any("sender" in (t.label or "").lower() and "email" in (t.label or "").lower() for t in at.text_input)


# ------------------------------------------------------------------ Emails tab
def test_nothing_open_until_a_row_is_chosen(app_env):
    at = start()
    assert not [b for b in at.button if "Approve" in b.label]
    assert "Click a row" in texts(at)


def test_selected_email_shows_full_details(app_env):
    service, created = app_env
    at = start(created[0])
    shown = texts(at)
    assert "alice@example.org" in shown and "Hello Alice" in shown
    assert "Pending review" in shown and "PENDING_REVIEW" not in shown
    assert any("Your work on protein engineering" in t.value for t in at.text)  # full body
    assert "Not connected" in shown  # sender line


def test_table_uses_friendly_labels(app_env):
    at = start()
    frame = at.dataframe[0].value
    assert list(frame.columns) == ["Status", "Campaign", "Recipient", "Subject", "Last updated"]
    assert all("Pending review" in s for s in frame["Status"]) and "PENDING_REVIEW" not in str(frame)


def test_approve_records_local_operator_and_keeps_email_open(app_env):
    service, created = app_env
    at = start(created[0])
    button(at, "Approve").click().run()
    assert not at.exception and not at.error
    first = service.get(created[0].draft.draft_id)
    assert first.draft.status is Status.APPROVED and first.draft.approval.reviewer == LOCAL_OPERATOR
    assert at.session_state[SELECTED] == created[0].draft.draft_id
    assert "Approved" in texts(at) and any("Reject" in b.label and b.disabled for b in at.button)


def test_email_stays_visible_when_filter_hides_it_after_approval(app_env):
    service, created = app_env
    at = start(created[0])
    at.multiselect(key="emails_status").set_value(["Pending review"]).run()
    button(at, "Approve").click().run()
    assert service.get(created[0].draft.draft_id).draft.status is Status.APPROVED
    assert "no longer matches the filters" in " ".join(i.value for i in at.info)
    assert any("Approved by" in s.value for s in at.success)


def test_filters_narrow_the_table(app_env):
    service, created = app_env
    service.reject(created[1].draft.draft_id, "x")
    at = start()
    at.multiselect(key="emails_status").set_value(["Rejected"]).run()
    assert list(at.dataframe[0].value["Recipient"]) == ["bob@example.org"]
    at.multiselect(key="emails_status").set_value([]).run()
    at.selectbox(key="emails_campaign").set_value("camp1").run()
    assert len(at.dataframe[0].value) == 2


def test_reject_with_reason(app_env):
    service, created = app_env
    at = start(created[0])
    at.text_input(key=f"reason_{created[0].draft.draft_id}").set_value("off topic").run()
    button(at, "Reject").click().run()
    assert service.get(created[0].draft.draft_id).draft.status is Status.REJECTED
    assert any("off topic" in (e.detail or "") for e in service.decisions(created[0].draft.draft_id))


def test_edit_after_approval_invalidates(app_env):
    service, created = app_env
    service.approve(created[0].draft.draft_id, LOCAL_OPERATOR, created[0].draft.fingerprint)
    at = start(created[0])
    button(at, "Edit").click().run()
    assert any("cancels the existing approval" in w.value for w in at.warning)
    at.text_area[0].set_value("Completely new body")
    next(b for b in at.button if b.label == "Save changes").click().run()
    after = service.get(created[0].draft.draft_id)
    assert after.draft.status is Status.DRAFT and after.draft.approval is None
    assert after.draft.body == "Completely new body"
    assert at.session_state[SELECTED] == created[0].draft.draft_id  # still open
    assert "Draft" in texts(at) and button(at, "Submit for review")
    assert [e.kind for e in service.decisions(created[0].draft.draft_id)][-1] == "APPROVAL_INVALIDATED"


def test_edit_cancel_changes_nothing(app_env):
    service, created = app_env
    at = start(created[0])
    button(at, "Edit").click().run()
    at.text_area[0].set_value("nope")
    next(b for b in at.button if b.label == "Cancel").click().run()
    assert service.get(created[0].draft.draft_id).draft.body == created[0].draft.body


def test_approval_history_is_shown(app_env):
    service, created = app_env
    service.approve(created[0].draft.draft_id, LOCAL_OPERATOR, created[0].draft.fingerprint)
    service.edit(created[0].draft.draft_id, LOCAL_OPERATOR, body="changed")
    at = start(created[0])
    history = at.dataframe[1].value
    assert list(history["Decision"]) == ["Approved", "Approval cancelled by an edit"]
    assert set(history["By"]) == {LOCAL_OPERATOR}


def test_read_only_without_key(app_env, monkeypatch):
    service, created = app_env
    monkeypatch.delenv("OUTREACH_APPROVAL_KEY")
    monkeypatch.setattr("nucleate_outreach.settings.ROOT", Path("/nonexistent"))
    st.cache_resource.clear()
    at = start(created[0])
    assert button(at, "Approve").disabled
    assert service.get(created[0].draft.draft_id).draft.status is Status.PENDING_REVIEW
    assert any("Not set up" in m.value for m in at.markdown)  # Settings tab explains it


def test_sent_emails_cannot_be_edited(app_env):
    service, created = app_env
    service.approve(created[0].draft.draft_id, LOCAL_OPERATOR, created[0].draft.fingerprint)
    service.send(created[0].draft.draft_id)
    at = start(created[0])
    assert button(at, "Edit").disabled and button(at, "Approve").disabled
    assert "Simulated sent" in texts(at)


# ------------------------------------------------------------------ Campaigns tab
def test_campaign_metrics_and_simulated_send(app_env):
    service, created = app_env
    service.approve(created[0].draft.draft_id, LOCAL_OPERATOR, created[0].draft.fingerprint)
    at = start()
    metric = {m.label: m.value for m in at.metric}
    assert metric["Total drafts"] == "2" and metric["Pending review"] == "1" and metric["Approved"] == "1"
    button(at, "Run simulated send").click().run()
    assert not at.exception
    assert service.get(created[0].draft.draft_id).draft.status is Status.SENT
    assert service.get(created[1].draft.draft_id).draft.status is Status.PENDING_REVIEW  # never touched
    assert {m.label: m.value for m in at.metric}["Simulated sent"] == "1"


def test_campaign_activity_lists_what_happened(app_env):
    at = start()
    activity = next(d.value for d in at.dataframe if "What happened" in d.value.columns)
    assert "Created" in set(activity["What happened"])


# ------------------------------------------------------------------ Settings tab
def test_settings_show_status_but_never_the_key(app_env):
    at = start()
    page = texts(at) + " ".join(str(e.value) for e in at.get("markdown"))
    assert KEY not in page
    assert "Local prototype" in page and "Simulation only" in page and "Available" in page
    assert "Not connected" in page and "outreach.db" in page


# ------------------------------------------------------------------ Import tab
def test_import_contacts_with_library_template_creates_traceable_drafts(app_env):
    service, _ = app_env
    at = start()
    at.text_input(key="import_campaign").set_value("fresh-campaign").run()
    button(at, "Create emails").click().run()
    assert not at.exception
    created = service.list_drafts("fresh-campaign")
    assert len(created) == 3  # example file: 3 eligible fictional contacts
    meta = service.draft_meta(created[0].draft.draft_id)
    assert meta.source_kind == "template" and meta.template_version == 1
    assert all(s.draft.status is Status.PENDING_REVIEW for s in created)


def uploader(at, key):
    return at.get_by_key(key)


def open_draft_import(at):
    at.radio(key="import_mode").set_value("B. Complete email drafts").run()
    return at


def test_import_complete_drafts_through_the_ui(app_env):
    service, _ = app_env
    at = open_draft_import(start())
    uploader(at, "drafts_upload").set_value(("example_drafts.csv", example_csv(), "text/csv")).run()
    assert not at.exception and not at.error
    shown = {m.label: m.value for m in at.metric}
    assert shown["Ready to import"] == "2" and shown["Rows with problems"] == "0"
    assert any("Gründung" in str(v) for d in at.dataframe for v in d.value.get("Subject", []))  # preview, nothing saved
    assert service.list_drafts("example-campaign") == []
    button(at, "Import 2 email").click().run()
    imported = service.list_drafts("example-campaign")
    assert len(imported) == 2 and all(s.draft.status is Status.PENDING_REVIEW for s in imported)
    assert service.draft_meta(imported[0].draft.draft_id).source_kind == "imported"
    # the same file again: nothing left to import, nothing duplicated
    uploader(at, "drafts_upload").set_value(("example_drafts.csv", example_csv(), "text/csv")).run()
    assert {m.label: m.value for m in at.metric}["Already in the app"] == "2"
    assert not [b for b in at.button if "Import" in b.label and "email(s)" in b.label and not b.disabled]
    assert len(service.list_drafts("example-campaign")) == 2


def test_import_xlsx_through_the_ui(app_env):
    service, _ = app_env
    at = open_draft_import(start())
    uploader(at, "drafts_upload").set_value(("d.xlsx", example_xlsx(), "application/octet-stream")).run()
    button(at, "Import 2 email").click().run()
    assert len(service.list_drafts("example-campaign")) == 2


def test_import_shows_errors_before_importing_and_skips_bad_rows(app_env):
    service, _ = app_env
    bad = ("campaign,recipient_email,subject,body\n"
           "c9,good@example.org,Hi,Body\n"
           "c9,nonsense,Hi,Body\n").encode()
    at = open_draft_import(start())
    uploader(at, "drafts_upload").set_value(("d.csv", bad, "text/csv")).run()
    shown = {m.label: m.value for m in at.metric}
    assert shown["Ready to import"] == "1" and shown["Rows with problems"] == "1"
    assert any("invalid recipient" in str(m.value) for m in at.markdown)
    button(at, "Import 1 email").click().run()
    assert [s.draft.recipient for s in service.list_drafts("c9")] == ["good@example.org"]


def test_import_ui_refuses_a_file_with_missing_columns(app_env):
    service, _ = app_env
    at = open_draft_import(start())
    uploader(at, "drafts_upload").set_value(("d.csv", b"a,b\n1,2\n", "text/csv")).run()
    assert any("missing required column" in e.value for e in at.error)
    assert not [b for b in at.button if "email(s)" in b.label]


# ------------------------------------------------------------------ Templates tab
def test_templates_tab_lists_examples_and_saves_new_version(app_env):
    service, _ = app_env
    at = start()
    pick = at.selectbox(key="template_pick")
    template_id = pick.value
    versions = service.templates.versions(template_id)
    assert len(versions) == 1
    text = at.text_area(key=f"template_text_{template_id}_1")
    text.set_value(versions[0].content + "\nP.S. Added in a test.\n").run()
    button(at, "Save new version").click().run()
    assert not at.exception
    assert [v.version for v in service.templates.versions(template_id)] == [2, 1]
    assert service.templates.get(template_id, 1).content == versions[0].content
    assert any(d.label.startswith("⬇️") for d in at.get("download_button"))


def test_invalid_template_edit_cannot_be_saved(app_env):
    service, _ = app_env
    at = start()
    template_id = at.selectbox(key="template_pick").value
    at.text_area(key=f"template_text_{template_id}_1").set_value("no subject line here").run()
    assert button(at, "Save new version").disabled
    assert any("Subject:" in e.value for e in at.error)


def test_template_upload_saves_a_validated_template(app_env):
    service, _ = app_env
    at = start()
    content = "Subject: Hallo {{first_name}}\nSchön, {{name}} von {{institution}}!\n{{sender_name}}".encode()
    uploader(at, "template_upload").set_value(("my_template.md", content, "text/markdown")).run()
    assert not at.error
    button(at, "Save template").click().run()
    saved = service.templates.find_by_name("My template")
    assert saved is not None and "Schön" in service.templates.get(saved.template_id).content
    assert at.selectbox(key="template_pick").value == saved.template_id  # the new template is opened


def test_template_upload_rejects_bad_files(app_env):
    service, _ = app_env
    at = start()
    before = len(service.templates.list())
    uploader(at, "template_upload").set_value(("t.txt", b"Hello without a subject", "text/plain")).run()
    assert any("Subject:" in e.value for e in at.error)
    assert button(at, "Save template").disabled
    uploader(at, "template_upload").set_value(("t.txt", b"Subject: Hi {{bogus}}\nBody", "text/plain")).run()
    assert any("Unknown variable" in e.value for e in at.error)
    assert len(service.templates.list()) == before


# ------------------------------------------------------------------ create a template in the dashboard
def fill_new_template(at, name="Pasted intro", subject="Hello {{first_name}}",
                      body="Dear {{name}},\n\nYour work in {{research_area}} at {{institution}}.\n\n{{sender_name}}"):
    at.text_input(key="new_tpl_name_0").set_value(name)
    at.text_input(key="new_tpl_subject_0").set_value(subject)
    at.text_area(key="new_tpl_body_0").set_value(body).run()


def test_create_template_shows_preview_then_saves_as_version_one(app_env):
    service, _ = app_env
    at = start()
    fill_new_template(at)
    assert not at.error
    assert any("Hello Alex" in m.value for m in at.markdown)  # preview with a fictional person
    assert service.templates.find_by_name("Pasted intro") is None  # nothing saved yet
    at.get_by_key("new_tpl_save_0").click().run()
    saved = service.templates.find_by_name("Pasted intro")
    assert saved.latest_version == 1
    stored = service.templates.get(saved.template_id)
    assert stored.content.startswith("Subject: Hello {{first_name}}\nDear {{name}},")
    assert at.selectbox(key="template_pick").value == saved.template_id
    assert at.text_input(key="new_tpl_name_1").value == ""  # form emptied for the next template


def test_create_template_keeps_pasted_multiline_unicode_text(app_env):
    service, _ = app_env
    at = start()
    body = "Liebe {{name}},\n\n  zweite Zeile – Übung 🙂\n\nGrüße\n{{sender_name}}"
    fill_new_template(at, name="Deutsch", subject="Einladung für {{first_name}}", body=body)
    at.get_by_key("new_tpl_save_0").click().run()
    saved = service.templates.find_by_name("Deutsch")
    assert service.templates.get(saved.template_id).content.endswith(body + "\n")


@pytest.mark.parametrize("name, subject, body, fragment", [
    ("", "Hi", "body", "template name"),
    ("T", "", "body", "email subject"),
    ("T", "Hi", "", "email text"),
    ("T", "Hi {{bogus}}", "body", "Unknown variable"),
    ("T", "Hi", "Dear {{nope}}", "Unknown variable"),
])
def test_create_template_rejects_invalid_input(app_env, name, subject, body, fragment):
    service, _ = app_env
    before = len(service.templates.list())
    at = start()
    at.text_input(key="new_tpl_name_0").set_value(name)
    at.text_input(key="new_tpl_subject_0").set_value(subject)
    at.text_area(key="new_tpl_body_0").set_value(body).run()
    assert any(fragment in e.value for e in at.error)
    assert at.get_by_key("new_tpl_save_0").disabled
    assert len(service.templates.list()) == before


def test_create_template_refuses_an_existing_name(app_env):
    service, _ = app_env
    existing = service.templates.list()[0]
    at = start()
    fill_new_template(at, name=existing.name.lower())
    assert any("already exists" in e.value for e in at.error)
    assert at.get_by_key("new_tpl_save_0").disabled


def test_new_template_is_usable_in_import_and_edit_makes_version_two(app_env):
    service, _ = app_env
    at = start()
    fill_new_template(at)
    at.get_by_key("new_tpl_save_0").click().run()
    saved = service.templates.find_by_name("Pasted intro")
    # editing creates version 2 and leaves version 1 untouched
    original = service.templates.get(saved.template_id, 1).content
    at.text_area(key=f"template_text_{saved.template_id}_1").set_value(original + "\nPS: new line\n").run()
    button(at, "Save new version").click().run()
    assert [v.version for v in service.templates.versions(saved.template_id)] == [2, 1]
    assert service.templates.get(saved.template_id, 1).content == original
    # it is offered in the Import tab (latest version) and drafts trace back to it
    choice = at.selectbox(key="import_template")
    assert any("Pasted intro (version 2)" in str(o) for o in choice.options)
    choice.select_index(next(i for i, o in enumerate(choice.options) if "Pasted intro" in str(o))).run()
    at.text_input(key="import_campaign").set_value("pasted-campaign").run()
    button(at, "Create emails").click().run()
    drafts = service.list_drafts("pasted-campaign")
    assert len(drafts) == 3
    meta = service.draft_meta(drafts[0].draft.draft_id)
    assert (meta.template_name, meta.template_version) == ("Pasted intro", 2)
    assert "PS: new line" in drafts[0].draft.body
