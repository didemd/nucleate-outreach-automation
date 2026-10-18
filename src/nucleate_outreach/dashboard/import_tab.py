"""Import tab: (A) contact list + template, or (B) complete drafts written elsewhere."""

from __future__ import annotations

import tempfile
from pathlib import Path

import streamlit as st

from nucleate_outreach.contacts import load_contacts_csv
from nucleate_outreach.draft_import import (EXAMPLE_CONTACTS_CSV, example_csv, example_xlsx, plan_import)
from nucleate_outreach.service import ReviewService
from nucleate_outreach.settings import LOCAL_OPERATOR, ROOT
from nucleate_outreach.templating import TemplateError, render_email

from .common import EXPECTED, flash

OPTION_A = "A. Contact list + a template"
OPTION_B = "B. Complete email drafts"


def render(service: ReviewService) -> None:
    st.caption("Use fictional contacts only in this prototype. Imported emails always start as **Pending review**; "
               "nothing is sent.")
    choice = st.radio("What do you want to import?", [OPTION_A, OPTION_B], horizontal=True, key="import_mode")
    st.divider()
    if choice == OPTION_A:
        _contacts_and_template(service)
    else:
        _complete_drafts(service)


# ------------------------------------------------------------------ option A
def _contacts_and_template(service: ReviewService) -> None:
    st.markdown("Upload a list of people. The app fills a template for each one who is eligible for outreach.")
    source = st.radio("Contact list", ["Example list (fictional)", "Upload my own CSV"], horizontal=True,
                      key="contacts_source")
    st.download_button("Download an example contact file", EXAMPLE_CONTACTS_CSV.encode("utf-8"),
                       "example_contacts.csv", "text/csv", key="dl_contacts")
    data: bytes | None = None
    if source.startswith("Example"):
        data = (ROOT / "examples" / "example_contacts.csv").read_bytes()
    else:
        upload = st.file_uploader("Contact CSV (columns: name, institution, email, research_area, outreach_eligible)",
                                  type="csv", key="contacts_upload")
        data = upload.getvalue() if upload else None
    if data is None:
        return
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "contacts.csv"
        path.write_bytes(data)
        try:
            result = load_contacts_csv(path)
        except (ValueError, UnicodeDecodeError) as exc:
            st.error(f"Could not read the file: {exc}")
            return
    st.write(f"**{len(result.contacts)}** valid contacts, **{len(result.eligible)}** eligible for outreach.")
    for title, issues in (("Rows with problems", result.invalid), ("Duplicates", result.duplicates),
                          ("Warnings", result.warnings)):
        if issues:
            with st.expander(f"{title} ({len(issues)})"):
                for i in issues:
                    st.write(f"Row {i.row}: {i.message}")

    templates = service.templates.list()
    if not templates:
        st.warning("There are no templates yet. Add one in the **Templates** tab first.")
        return
    summary = st.selectbox("Template", templates, key="import_template",
                           format_func=lambda t: f"{t.name} (version {t.latest_version})")
    template = service.templates.get(summary.template_id)
    campaign = st.text_input("Campaign name", "activator-demo-2026", key="import_campaign")
    sender_name = st.text_input("Signature name", "Nucleate Germany Team", key="import_sender_name",
                                help="Printed at the end of each email as {{sender_name}}. It is only text: "
                                     "it does not choose or verify the sending account.")

    if result.eligible:
        with st.expander("Preview the first email", expanded=True):
            try:
                subject, body = render_email(template.content, result.eligible[0], sender_name)
                st.markdown(f"**To:** {result.eligible[0].email}  \n**Subject:** {subject}")
                st.text(body)
            except TemplateError as exc:
                st.error(f"This template can't be filled for the first contact: {exc}")
    if st.button("Create emails", type="primary", key="create_drafts", disabled=not result.eligible):
        try:
            report = service.create_drafts(result.eligible, template.content, sender_name, campaign,
                                           LOCAL_OPERATOR, template=template)
            flash("success", f"Created {len(report.created)} emails waiting for review "
                             f"(template “{template.name}”, version {template.version}). "
                             f"Skipped {len(report.skipped_existing)} that already existed in this campaign.")
        except EXPECTED as exc:
            flash("error", str(exc))
        st.rerun()


# ------------------------------------------------------------------ option B
def _complete_drafts(service: ReviewService) -> None:
    st.markdown("Import emails that are already written — for example with ChatGPT, Claude Chat or by hand. "
                "The subject and text are kept **exactly** as written.")
    with st.expander("What should the file look like?"):
        st.markdown(
            "One row per email. Columns:\n\n"
            "- **campaign** (campaign name) — or fill in the default below\n"
            "- **contact_id** (optional)\n"
            "- **recipient_email**\n"
            "- **recipient_name** (optional)\n"
            "- **subject**\n"
            "- **body** (the full email, line breaks are fine)\n"
            "- **personalization_notes** (optional, for your reference)\n\n"
            "Columns such as status or approval are ignored: every email must still be approved by a person here.")
    d1, d2 = st.columns(2)
    d1.download_button("Download example (CSV)", example_csv(), "example_drafts.csv", "text/csv", key="dl_ex_csv")
    d2.download_button("Download example (Excel)", example_xlsx(), "example_drafts.xlsx",
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="dl_ex_xlsx")

    upload = st.file_uploader("Your file (.csv or .xlsx)", type=["csv", "xlsx"], key="drafts_upload")
    default_campaign = st.text_input("Default campaign (used when a row has no campaign)", "", key="drafts_default_campaign")
    if upload is None:
        return
    try:
        plan = plan_import(upload.name, upload.getvalue(), service.draft_exists, default_campaign)
    except ValueError as exc:
        st.error(str(exc))
        return

    for warning in plan.file_warnings:
        st.warning(warning)
    m1, m2, m3 = st.columns(3)
    m1.metric("Ready to import", len(plan.ready))
    m2.metric("Already in the app", len(plan.already_exists))
    m3.metric("Rows with problems", len(plan.errors))
    if plan.errors:
        with st.expander(f"Rows with problems ({len(plan.errors)}) — these will be skipped", expanded=True):
            for e in plan.errors:
                st.write(f"Row {e.row}: {e.message}")
    if plan.already_exists:
        with st.expander(f"Already in the app ({len(plan.already_exists)}) — these will be skipped"):
            for e in plan.already_exists:
                st.write(f"Row {e.row}: {e.message}")

    if plan.ready:
        st.markdown("**Preview**")
        st.dataframe([{"Row": r.row, "Campaign": r.campaign, "Recipient": r.recipient_email,
                       "Subject": r.subject, "Starts with": r.body[:80].replace("\n", " ")} for r in plan.ready],
                     hide_index=True)
        row = st.selectbox("Read a full email before importing", plan.ready, key="drafts_preview_row",
                           format_func=lambda r: f"Row {r.row} — {r.recipient_email}")
        with st.container(border=True):
            st.markdown(f"**To:** {row.recipient_email}  \n**Subject:** {row.subject}")
            st.divider()
            st.text(row.body)
            if row.notes:
                st.caption(f"Notes: {row.notes}")
    label = f"Import {len(plan.ready)} email(s) for review"
    if st.button(label, type="primary", key="import_drafts", disabled=not plan.ready):
        try:
            report = service.import_drafts(plan.ready, LOCAL_OPERATOR, upload.name)
            flash("success", f"Imported {len(report.created)} email(s). They are waiting in the Emails tab "
                             f"as “Pending review”. Skipped {len(report.skipped_existing)} already in the app.")
        except EXPECTED as exc:
            flash("error", str(exc))
        st.rerun()
