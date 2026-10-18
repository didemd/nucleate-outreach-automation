"""Templates tab: a reusable, versioned library of email templates."""

from __future__ import annotations

import re

import streamlit as st

from nucleate_outreach.service import ReviewService
from nucleate_outreach.template_library import (ALLOWED_EXTENSIONS, KNOWN_VARIABLES, TemplateLibrary,
                                                compose_template, decode_upload, preview_text, validate_template_text, variables_in)
from nucleate_outreach.templating import TemplateError

from .common import EXPECTED, flash
from .view import pretty_time

PENDING_PICK = "_template_pick_pending"


def _file_name(name: str, version: int) -> str:
    return f"{re.sub(r'[^A-Za-z0-9._-]+', '-', name).strip('-').lower() or 'template'}-v{version}.txt"


def render(service: ReviewService) -> None:
    lib = service.templates
    st.markdown("Templates are reusable email texts with fill-in variables such as `{{name}}`, `{{institution}}` "
                "and `{{research_area}}`. Write them yourself or with an AI chat, then save them here.")
    _create(lib)
    _upload(lib)
    templates = lib.list()
    if not templates:
        st.info("No templates yet. Upload one above.")
        return
    if PENDING_PICK in st.session_state:  # set by an action; applied before the widget exists
        st.session_state["template_pick"] = st.session_state.pop(PENDING_PICK)
    ids = [t.template_id for t in templates]
    if st.session_state.get("template_pick") not in ids:
        st.session_state["template_pick"] = ids[0]
    names = {t.template_id: t for t in templates}
    pick = st.selectbox("Saved templates", ids, key="template_pick",
                        format_func=lambda i: f"{names[i].name} — version {names[i].latest_version}"
                                              + (" · example" if names[i].is_example else ""))
    versions = lib.versions(pick)
    version_numbers = [v.version for v in versions]
    chosen = st.selectbox("Version", version_numbers, key=f"template_version_{pick}",
                          format_func=lambda n: f"Version {n}" + (" (latest)" if n == version_numbers[0] else ""))
    current = next(v for v in versions if v.version == chosen)
    st.caption(f"Saved {pretty_time(current.created_at)}"
               + (f" · {current.note}" if current.note else "")
               + (f" · from file {current.source_file}" if current.source_file else ""))

    used = variables_in(current.content)
    st.markdown("**Variables used:** " + (", ".join(f"`{{{{{v}}}}}`" for v in used) if used else "none"))
    st.code(current.content, language=None, wrap_lines=True)
    st.caption("To copy: use the copy icon at the top-right corner of the box above.")
    if st.toggle("Show an example with a fictional person filled in", key=f"template_example_{pick}_{chosen}"):
        try:
            subject, body = preview_text(current.content)
            with st.container(border=True):
                st.markdown(f"**Subject:** {subject}")
                st.divider()
                st.text(body)
        except TemplateError as exc:
            st.error(str(exc))
    st.download_button("⬇️ Download this version", current.content.encode("utf-8"),
                       _file_name(current.name, current.version), "text/plain", key=f"template_dl_{pick}_{chosen}")

    with st.expander("✏️ Edit and save as a new version"):
        st.caption("Earlier versions are never overwritten. Emails already made keep pointing at the version "
                   "they were made from.")
        text = st.text_area("Template text", current.content, height=320, key=f"template_text_{pick}_{chosen}")
        note = st.text_input("What changed? (optional)", key=f"template_note_{pick}_{chosen}")
        problems = validate_template_text(text)
        for p in problems:
            st.error(p)
        if st.button("Save new version", type="primary", key=f"template_save_{pick}_{chosen}",
                     disabled=bool(problems) or text == current.content):
            try:
                saved = lib.save_new_version(pick, text, note)
                flash("success", f"Saved “{saved.name}” as version {saved.version}.")
            except EXPECTED as exc:
                flash("error", str(exc))
            st.rerun()


def _upload(lib: TemplateLibrary) -> None:
    with st.expander("➕ Add a template from a file (.txt or .md)"):
        st.caption("The first line must be `Subject: ...`; the rest is the email text. "
                   "Allowed variables: " + ", ".join(f"`{{{{{v}}}}}`" for v in KNOWN_VARIABLES) + ".")
        upload = st.file_uploader("Template file", type=[e.lstrip(".") for e in ALLOWED_EXTENSIONS],
                                  key="template_upload")
        if upload is None:
            return
        if st.session_state.get("_template_saved_file") == upload.file_id:
            st.success("This file has been saved. Remove it above to add another.")
            return
        try:
            text = decode_upload(upload.name, upload.getvalue())
        except TemplateError as exc:
            st.error(str(exc))
            return
        problems = validate_template_text(text)
        for p in problems:
            st.error(p)
        st.code(text, language=None, wrap_lines=True)
        default_name = re.sub(r"[_-]+", " ", upload.name.rsplit(".", 1)[0]).strip().capitalize()
        name = st.text_input("Template name", default_name, key=f"template_name_{upload.file_id}")
        existing = lib.find_by_name(name) if name.strip() else None
        if existing:
            st.info(f"A template called “{existing.name}” already exists. Saving adds version "
                    f"{existing.latest_version + 1}.")
        if st.button("Save template", type="primary", key="template_add", disabled=bool(problems)):
            try:
                if existing:
                    saved = lib.save_new_version(existing.template_id, text, "Uploaded file", upload.name)
                else:
                    saved = lib.create(name, text, "Uploaded file", upload.name)
                st.session_state[PENDING_PICK] = saved.template_id
                st.session_state["_template_saved_file"] = upload.file_id
                flash("success", f"Saved “{saved.name}” (version {saved.version}).")
            except EXPECTED as exc:
                flash("error", str(exc))
            st.rerun()


def _create(lib: TemplateLibrary) -> None:
    """Write or paste a template directly in the browser (no file needed)."""
    nonce = st.session_state.get("_new_template_nonce", 0)  # bumping it empties the fields after saving
    with st.expander("📝 Create new template"):
        st.caption("Type or paste your email text. Use variables such as "
                   + ", ".join(f"`{{{{{v}}}}}`" for v in KNOWN_VARIABLES) + ".")
        name = st.text_input("Template name", key=f"new_tpl_name_{nonce}", placeholder="e.g. Activator invitation")
        subject = st.text_input("Email subject", key=f"new_tpl_subject_{nonce}",
                                placeholder="e.g. An invitation for {{first_name}}")
        body = st.text_area("Email text", key=f"new_tpl_body_{nonce}", height=280,
                            placeholder="Dear {{name}},\n\nYour work in {{research_area}} at {{institution}} ...")
        if not (name.strip() or subject.strip() or body.strip()):
            return
        problems: list[str] = []
        content = ""
        if not name.strip():
            problems.append("Please enter a template name.")
        try:
            content = compose_template(subject, body)
            problems += validate_template_text(content)
        except TemplateError as exc:
            problems.append(str(exc))
        existing = lib.find_by_name(name) if name.strip() else None
        if existing:
            problems.append(f"A template called “{existing.name}” already exists. Choose another name, or open it "
                            "below and use “Edit and save as a new version”.")
        for p in problems:
            st.error(p)
        if content and not any("Unknown variable" in p or "Subject" in p for p in problems):
            st.markdown("**Preview** (filled with a fictional person)")
            try:
                shown_subject, shown_body = preview_text(content)
                with st.container(border=True):
                    st.markdown(f"**Subject:** {shown_subject}")
                    st.divider()
                    st.text(shown_body)
            except TemplateError as exc:
                st.error(str(exc))
        if st.button("Save template", type="primary", key=f"new_tpl_save_{nonce}", disabled=bool(problems)):
            try:
                saved = lib.create(name, content, "Written in the dashboard")
                st.session_state[PENDING_PICK] = saved.template_id
                st.session_state["_new_template_nonce"] = nonce + 1
                flash("success", f"Saved “{saved.name}” as version {saved.version}. "
                                 "You can now pick it in the Import tab.")
            except EXPECTED as exc:
                flash("error", str(exc))
            st.rerun()
