"""Settings tab: read-only facts about how the app is set up. Never shows secrets."""

from __future__ import annotations

import streamlit as st

from nucleate_outreach.sender_identity import current_sender_identity
from nucleate_outreach.service import ReviewService
from nucleate_outreach.settings import LOCAL_OPERATOR, Settings


def render(service: ReviewService) -> None:
    settings = Settings.load()
    identity = current_sender_identity()
    rows = [
        ("Mode", "Local prototype — one person, this computer only"),
        ("Sending", "Simulation only — no real email is ever sent"),
        ("Gmail connection", identity.headline),
        ("Approval key", "✅ Available — approving is switched on" if service.can_approve
         else "❌ Not set up — approving is switched off (read-only). Run `nucleate-dashboard init-key`."),
        ("Database file", str(settings.db_path)),
        ("Review identity", f"“{LOCAL_OPERATOR}” — a label, not a login"),
    ]
    for name, value in rows:
        a, b = st.columns([1, 3])
        a.markdown(f"**{name}**")
        b.markdown(value)
    st.divider()
    st.caption("The approval key itself is never shown here. It lives in the private `.env` file, which Git ignores. "
               "Only the computer running this app can open the page (address 127.0.0.1).")
