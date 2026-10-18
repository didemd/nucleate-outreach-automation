"""Small pieces shared by every tab: the service, flash messages and the sender banner."""

from __future__ import annotations

import streamlit as st

from nucleate_outreach.drafts import InvalidTransition
from nucleate_outreach.sender import SendBlocked
from nucleate_outreach.sender_identity import SenderIdentity
from nucleate_outreach.service import PermissionDenied, ReviewService
from nucleate_outreach.settings import Settings
from nucleate_outreach.store import StoreError
from nucleate_outreach.templating import TemplateError

# Errors we expect and show politely instead of a crash screen.
EXPECTED = (ValueError, InvalidTransition, SendBlocked, PermissionDenied, StoreError, TemplateError)


@st.cache_resource
def get_service() -> ReviewService:
    return ReviewService.from_settings(Settings.load())


def flash(kind: str, message: str) -> None:
    """Remember a message to show after the next redraw. kind: success | error | info | warning"""
    st.session_state["flash"] = (kind, message)


def show_flash() -> None:
    if "flash" in st.session_state:
        kind, message = st.session_state.pop("flash")
        getattr(st, kind)(message)


def run(action, success: str) -> None:
    """Run a backend action, remember the result, and redraw."""
    try:
        action()
        flash("success", success)
    except EXPECTED as exc:
        flash("error", str(exc))
    st.rerun()


def render_sender_banner(identity: SenderIdentity) -> None:
    """The always-visible 'who would this be sent from' box. It only displays; nobody can type an address here."""
    with st.container(border=True):
        a, b, c = st.columns([2, 2, 1.4])
        a.caption("Sending account")
        a.markdown(("🟢 " if identity.connected else "⚪ ") + f"**{identity.headline}**")
        b.caption("Sending mode")
        b.markdown(identity.sending_mode)
        c.caption("Last verified")
        c.markdown(identity.last_verified_at or "—")
