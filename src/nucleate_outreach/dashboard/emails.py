"""Emails tab: the review queue and the details of the selected email."""

from __future__ import annotations

import streamlit as st

from nucleate_outreach.drafts import Status
from nucleate_outreach.service import ReviewService
from nucleate_outreach.settings import LOCAL_OPERATOR
from nucleate_outreach.store import DraftNotFound

from .common import run
from .view import (LABEL_TO_STATUS, STATUS_ICON, decision_rows, pretty_time, queue_rows, resolve_selection,
                   status_label)

SELECTED = "selected_draft"  # session key holding the open email's id


def render(service: ReviewService) -> None:
    campaigns = service.store.campaigns()
    c1, c2 = st.columns(2)
    campaign = c1.selectbox("Campaign", ["All campaigns"] + campaigns, key="emails_campaign")
    wanted = c2.multiselect("Status", list(LABEL_TO_STATUS), key="emails_status",
                            placeholder="All statuses")
    drafts = service.list_drafts(None if campaign == "All campaigns" else campaign,
                                 [LABEL_TO_STATUS[w] for w in wanted] or None)

    if not drafts:
        st.info("No emails match these filters yet. Use the **Import** tab to add some.")
    else:
        st.caption("Click a row to open the email below.")
        table = st.dataframe(queue_rows(drafts), hide_index=True, on_select="rerun",
                             selection_mode="single-row", key="emails_table")
        selected, last = resolve_selection(drafts, list(table.selection.rows), st.session_state.get(SELECTED),
                                           st.session_state.get("_last_clicked"))
        st.session_state[SELECTED], st.session_state["_last_clicked"] = selected, last

    draft_id = st.session_state.get(SELECTED)
    if not draft_id:
        return
    st.divider()
    try:
        stored = service.get(draft_id)
    except DraftNotFound:
        st.session_state.pop(SELECTED, None)
        return
    if drafts and stored.draft.draft_id not in {d.draft.draft_id for d in drafts}:
        st.info("This email no longer matches the filters above, but is kept open so you can see what happened.")
    _details(service, stored)


def _details(service: ReviewService, stored) -> None:
    draft = stored.draft
    st.subheader(f"{STATUS_ICON[draft.status]} {status_label(draft.status)}")
    st.caption(f"Campaign: {draft.campaign_id} · Last updated {pretty_time(stored.updated_at)}")

    valid = service.approval_is_valid(stored)
    if draft.approval:
        a = draft.approval
        who = f"Approved by **{a.reviewer}** · {pretty_time(a.approved_at)}"
        if valid is True:
            st.success(who + " · approval checked against the current text ✔")
        elif valid is False:
            st.error(who + " · **this approval does not match the current text; sending is blocked.**")
        else:
            st.warning(who + " · cannot be checked (no approval key configured).")

    with st.container(border=True):
        st.markdown("**From:** Not connected — simulated sending only")
        st.markdown(f"**To:** {draft.recipient}")
        st.markdown(f"**Subject:** {draft.subject}")
        st.divider()
        st.text(draft.body)
    _source_line(service, draft.draft_id)

    # ---- actions
    editing_key = f"editing_{draft.draft_id}"
    pending = draft.status is Status.PENDING_REVIEW
    reason = ""
    if pending:
        reason = st.text_input("Reason for rejecting (optional)", key=f"reason_{draft.draft_id}")
    b1, b2, b3, b4 = st.columns(4)
    if b1.button("✏️ Edit", key=f"edit_btn_{draft.draft_id}", disabled=draft.status is Status.SENT,
                 help="Sent emails cannot be edited." if draft.status is Status.SENT else None):
        st.session_state[editing_key] = True
        st.rerun()
    if b2.button("✅ Approve", type="primary", key=f"approve_{draft.draft_id}",
                 disabled=not (pending and service.can_approve)):
        run(lambda: service.approve(draft.draft_id, LOCAL_OPERATOR, draft.fingerprint), "Email approved.")
    if b3.button("⛔ Reject", key=f"reject_{draft.draft_id}", disabled=not pending):
        run(lambda: service.reject(draft.draft_id, LOCAL_OPERATOR, reason), "Email rejected.")
    if draft.status is Status.DRAFT and b4.button("Submit for review", key=f"submit_{draft.draft_id}"):
        run(lambda: service.submit_for_review(draft.draft_id, LOCAL_OPERATOR), "Sent to the review queue.")
    if draft.status in (Status.REJECTED, Status.FAILED) and b4.button("Reopen as draft", key=f"reopen_{draft.draft_id}"):
        run(lambda: service.reopen(draft.draft_id, LOCAL_OPERATOR), "Reopened as a draft.")
    if pending and not service.can_approve:
        st.warning("Approving is switched off because no approval key is set up. See the **Settings** tab.")

    if st.session_state.get(editing_key) and draft.status is not Status.SENT:
        _edit_form(service, stored, editing_key)

    # ---- history
    st.markdown("##### Approval history")
    decisions = service.decisions(draft.draft_id)
    if decisions:
        st.dataframe(decision_rows(decisions), hide_index=True)
    else:
        st.caption("No approval decisions yet.")
    with st.expander("Everything that happened to this email"):
        st.dataframe(decision_rows(service.events(draft.draft_id)), hide_index=True)
    st.caption(f"Decisions are recorded as “{LOCAL_OPERATOR}”. This is a single-user local prototype: "
               "it does not verify who you are.")


def _source_line(service: ReviewService, draft_id: str) -> None:
    meta = service.draft_meta(draft_id)
    if meta is None:
        return
    if meta.source_kind == "template":
        st.caption(f"Made from template “{meta.template_name}”, version {meta.template_version}.")
    else:
        st.caption(f"Imported ready-made draft from file “{meta.source_file}”"
                   + (f" · contact ID {meta.contact_id}" if meta.contact_id else "") + ".")
    if meta.notes:
        st.caption(f"Notes from the file: {meta.notes}")


def _edit_form(service: ReviewService, stored, editing_key: str) -> None:
    draft = stored.draft
    with st.form(f"edit-{draft.draft_id}-{stored.version}"):
        st.markdown("**Edit this email**")
        recipient = st.text_input("To", draft.recipient)
        subject = st.text_input("Subject", draft.subject)
        body = st.text_area("Body", draft.body, height=320)
        if draft.status in (Status.APPROVED, Status.PENDING_REVIEW):
            st.warning("Saving a change "
                       + ("cancels the existing approval and " if draft.approval else "")
                       + "turns this email back into a Draft. You will need to send it for review again.")
        save, cancel = st.columns(2)
        saved = save.form_submit_button("Save changes", type="primary")
        cancelled = cancel.form_submit_button("Cancel")
    if cancelled:
        st.session_state.pop(editing_key, None)
        st.rerun()
    if saved:
        st.session_state.pop(editing_key, None)
        run(lambda: service.edit(draft.draft_id, LOCAL_OPERATOR, recipient=recipient, subject=subject,
                                 body=body), "Changes saved.")
