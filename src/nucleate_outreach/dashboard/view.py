"""Plain-Python helpers for the dashboard (no Streamlit), so they are easy to test.

They translate internal values into the wording a non-technical person expects.
"""

from __future__ import annotations

from datetime import datetime

from nucleate_outreach.drafts import Status
from nucleate_outreach.store import Event, StoredDraft

STATUS_LABEL = {
    Status.DRAFT: "Draft",
    Status.PENDING_REVIEW: "Pending review",
    Status.APPROVED: "Approved",
    Status.REJECTED: "Rejected",
    Status.SENT: "Simulated sent",
    Status.FAILED: "Failed",
}
STATUS_ICON = {Status.DRAFT: "📝", Status.PENDING_REVIEW: "🕒", Status.APPROVED: "✅",
               Status.REJECTED: "⛔", Status.SENT: "📨", Status.FAILED: "⚠️"}
LABEL_TO_STATUS = {label: status for status, label in STATUS_LABEL.items()}

EVENT_LABEL = {
    "CREATED": "Created", "STATUS": "Status changed", "EDITED": "Edited",
    "APPROVED": "Approved", "REJECTED": "Rejected", "APPROVAL_INVALIDATED": "Approval cancelled by an edit",
    "SEND_STARTED": "Simulated send started", "SEND_SUCCEEDED": "Simulated sent",
    "SEND_FAILED": "Simulated send failed", "SEND_UNCERTAIN": "Send outcome unknown",
    "SEND_ABORTED": "Send stopped before delivery",
}
ACTIVITY_FILTERS = {
    "Created": {"CREATED"}, "Reviewed": {"APPROVED", "REJECTED", "APPROVAL_INVALIDATED"},
    "Edited": {"EDITED"},
    "Sending": {"SEND_STARTED", "SEND_SUCCEEDED", "SEND_FAILED", "SEND_UNCERTAIN", "SEND_ABORTED"},
}


def status_label(status: Status) -> str:
    return STATUS_LABEL[status]


def pretty_time(iso: str | None) -> str:
    if not iso:
        return ""
    try:
        return datetime.fromisoformat(iso).strftime("%d %b %Y, %H:%M UTC")
    except ValueError:
        return iso


def queue_rows(drafts: list[StoredDraft]) -> list[dict[str, str]]:
    return [{"Status": f"{STATUS_ICON[s.draft.status]} {STATUS_LABEL[s.draft.status]}",
             "Campaign": s.draft.campaign_id, "Recipient": s.draft.recipient,
             "Subject": s.draft.subject, "Last updated": pretty_time(s.updated_at)}
            for s in drafts]


def resolve_selection(drafts: list[StoredDraft], clicked_rows: list[int], current_id: str | None,
                      last_clicked_id: str | None) -> tuple[str | None, str | None]:
    """Decide which email is open. Returns (selected_draft_id, last_clicked_id).

    A new click on a row wins. With no click (for example the table redrew after
    an approval) the email that was open stays open, even if filters now hide it.
    """
    if clicked_rows and 0 <= clicked_rows[0] < len(drafts):
        clicked = drafts[clicked_rows[0]].draft.draft_id
        if clicked != last_clicked_id:
            return clicked, clicked
        return current_id or clicked, last_clicked_id
    return current_id, None


def decision_rows(events: list[Event]) -> list[dict[str, str]]:
    return [{"When": pretty_time(e.at), "Decision": EVENT_LABEL.get(e.kind, e.kind), "By": e.actor or "",
             "Note": e.detail or ""} for e in events]


def metrics_for(counts: dict[str, int], uncertain: int = 0) -> dict[str, int]:
    """Campaign numbers in the wording of the Campaigns tab. `counts` maps internal status -> number."""
    n = lambda s: counts.get(s.value, 0)  # noqa: E731
    return {
        "Total drafts": sum(counts.values()),
        "Pending review": n(Status.PENDING_REVIEW),
        "Approved": n(Status.APPROVED),
        "Rejected": n(Status.REJECTED),
        "Simulated sent": n(Status.SENT),
        "Failed or uncertain": n(Status.FAILED) + uncertain,
    }
