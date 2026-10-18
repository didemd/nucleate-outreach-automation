"""Campaigns tab: simple numbers, recent activity and the simulated-sending controls."""

from __future__ import annotations

import streamlit as st

from nucleate_outreach.drafts import Status
from nucleate_outreach.service import ReviewService
from nucleate_outreach.settings import LOCAL_OPERATOR

from .common import run, flash
from .view import ACTIVITY_FILTERS, EVENT_LABEL, metrics_for, pretty_time


def render(service: ReviewService) -> None:
    progress = service.campaign_progress()
    if not progress:
        st.info("No campaigns yet. Import contacts or drafts in the **Import** tab to start one.")
        return
    uncertain = service.store.uncertain_counts()
    pick = st.selectbox("Campaign", ["All campaigns"] + sorted(progress), key="campaigns_pick")
    cid = None if pick == "All campaigns" else pick

    counts: dict[str, int] = {}
    for campaign, per_status in progress.items():
        if cid in (None, campaign):
            for status, n in per_status.items():
                counts[status] = counts.get(status, 0) + n
    unsure = sum(n for c, n in uncertain.items() if cid in (None, c))
    metrics = metrics_for(counts, unsure)
    for col, (name, value) in zip(st.columns(len(metrics)), metrics.items()):
        col.metric(name, value)
    if unsure:
        st.warning(f"{unsure} simulated send(s) have an unknown outcome and need a decision (see below).")

    st.markdown("##### All campaigns")
    st.dataframe([{"Campaign": c, **metrics_for(per, uncertain.get(c, 0)),
                   "Not yet submitted": per.get(Status.DRAFT.value, 0)}
                  for c, per in sorted(progress.items())], hide_index=True)

    st.markdown("##### Recent activity")
    kinds = st.multiselect("Show", list(ACTIVITY_FILTERS), key="campaigns_activity", placeholder="Everything")
    allowed = set().union(*(ACTIVITY_FILTERS[k] for k in kinds)) if kinds else None
    events = [(e, c, r) for e, c, r in service.store.recent_events(cid, 300)
              if allowed is None or e.kind in allowed][:30]
    if events:
        st.dataframe([{"When": pretty_time(e.at), "Campaign": c, "Recipient": r,
                       "What happened": EVENT_LABEL.get(e.kind, e.kind), "Note": e.detail or ""}
                      for e, c, r in events], hide_index=True)
    else:
        st.caption("Nothing to show yet.")

    _sending(service, cid)


def _sending(service: ReviewService, cid: str | None) -> None:
    st.markdown("##### Simulated sending")
    st.warning("SIMULATION ONLY — no real email is ever sent. This just tests the workflow.")
    approved = service.list_drafts(cid, [Status.APPROVED])
    st.write(f"**{len(approved)}** approved email(s) ready for a simulated send.")
    with st.expander("Testing options"):
        failing = st.multiselect("Pretend delivery fails for these recipients (to test error handling)",
                                 [s.draft.recipient for s in approved], key="campaigns_fail_for")
    if approved and st.button("Run simulated send for approved emails", type="primary", key="send_all",
                              disabled=not service.can_approve):
        outcomes = service.send_all_approved(cid, fail_for=set(failing))
        lines = []
        for draft_id, outcome in outcomes:
            who = service.get(draft_id).draft.recipient
            lines.append(f"{who}: {outcome if isinstance(outcome, str) else outcome.detail}")
        flash("info", "\n\n".join(lines))
        st.rerun()

    uncertain = [a for a in service.uncertain_attempts() if cid in (None, a.campaign_id)]
    if uncertain:
        st.markdown("**Needs a human decision**")
    for att in uncertain:
        st.error(f"The simulated send to **{att.recipient}** (campaign {att.campaign_id}) was interrupted: {att.detail}")
        note = st.text_input("Note (optional)", key=f"note-{att.attempt_id}")
        c1, c2 = st.columns(2)
        if c1.button("It WAS delivered", key=f"yes-{att.attempt_id}"):
            run(lambda: service.resolve_uncertain(att.attempt_id, True, LOCAL_OPERATOR, note), "Marked as sent.")
        if c2.button("It was NOT delivered", key=f"no-{att.attempt_id}"):
            run(lambda: service.resolve_uncertain(att.attempt_id, False, LOCAL_OPERATOR, note),
                "Marked as not sent; the email stays approved.")
