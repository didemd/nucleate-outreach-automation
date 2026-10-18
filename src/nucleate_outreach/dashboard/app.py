"""Streamlit dashboard. This file only lays out the page; all rules live in ReviewService."""

from __future__ import annotations

import streamlit as st

from nucleate_outreach.dashboard import campaigns, emails, import_tab, settings_tab, templates_tab
from nucleate_outreach.dashboard.common import get_service, render_sender_banner, show_flash
from nucleate_outreach.sender_identity import current_sender_identity

TABS = ["Emails", "Import", "Templates", "Campaigns", "Settings"]


def main() -> None:
    st.set_page_config(page_title="Nucleate Outreach", page_icon="✉️", layout="wide")
    service = get_service()
    st.title("✉️ Nucleate Outreach")
    render_sender_banner(current_sender_identity())
    show_flash()
    tabs = st.tabs(TABS)
    for tab, module in zip(tabs, (emails, import_tab, templates_tab, campaigns, settings_tab)):
        with tab:
            module.render(service)


main()
