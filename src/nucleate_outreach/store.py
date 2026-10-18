"""SQLite persistence for drafts, approvals, audit events and send attempts.

Design notes (for beginners):
  * One short-lived connection per operation. Streamlit runs code in several
    threads and SQLite connections must not be shared between them.
  * Write operations use BEGIN IMMEDIATE, which locks the database so two
    browser tabs can never interleave half-finished changes.
  * The database itself enforces key safety rules (unique indexes and CHECK
    constraints), so a bug in the UI cannot, for example, record two active
    sends to the same person in one campaign.
  * The store never decides whether an approval is *genuine*. That needs the
    secret key and stays in ApprovalService (Milestone 1). The store only
    saves and loads what it is given, and refuses obviously illegal changes.
"""

from __future__ import annotations

import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from .drafts import Approval, Draft, Status, now_iso

_STATUSES = ", ".join(f"'{s.value}'" for s in Status)

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS drafts (
    draft_id TEXT PRIMARY KEY,
    campaign_id TEXT NOT NULL,
    recipient TEXT NOT NULL,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ({_STATUSES})),
    version INTEGER NOT NULL DEFAULT 1,
    approval_fingerprint TEXT,
    approval_reviewer TEXT,
    approval_at TEXT,
    approval_signature TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    -- An APPROVED or SENT draft must carry a recorded approval.
    CHECK (status NOT IN ('APPROVED', 'SENT') OR approval_signature IS NOT NULL)
);
-- One draft per person per campaign.
CREATE UNIQUE INDEX IF NOT EXISTS ux_drafts_campaign_recipient
    ON drafts (campaign_id, lower(trim(recipient)));

-- Append-only audit trail. Rows are never updated or deleted by the app.
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    draft_id TEXT NOT NULL REFERENCES drafts (draft_id),
    at TEXT NOT NULL,
    kind TEXT NOT NULL,
    actor TEXT,
    detail TEXT,
    fingerprint TEXT
);

CREATE TABLE IF NOT EXISTS send_attempts (
    attempt_id TEXT PRIMARY KEY,
    draft_id TEXT NOT NULL REFERENCES drafts (draft_id),
    campaign_id TEXT NOT NULL,
    recipient TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('STARTED','SUCCEEDED','FAILED','UNCERTAIN','ABORTED')),
    started_at TEXT NOT NULL,
    finished_at TEXT,
    detail TEXT
);
-- Duplicate protection enforced by the database: at most ONE attempt per
-- person per campaign may be in progress, succeeded, or of unknown outcome.
CREATE UNIQUE INDEX IF NOT EXISTS ux_active_send
    ON send_attempts (campaign_id, recipient)
    WHERE state IN ('STARTED', 'SUCCEEDED', 'UNCERTAIN');

-- Where a draft came from (added in Milestone 3). Kept in its own table so the
-- drafts table, the approval fingerprint and old databases are untouched.
CREATE TABLE IF NOT EXISTS draft_meta (
    draft_id TEXT PRIMARY KEY REFERENCES drafts (draft_id),
    source_kind TEXT NOT NULL CHECK (source_kind IN ('template', 'imported')),
    template_id INTEGER,
    template_name TEXT,
    template_version INTEGER,
    source_file TEXT,
    contact_id TEXT,
    recipient_name TEXT,
    notes TEXT
);
"""


class StoreError(Exception):
    pass


class DraftNotFound(StoreError):
    pass


class ConcurrentModification(StoreError):
    """The draft changed since it was loaded (e.g. edited in another tab)."""


class DraftLocked(StoreError):
    """A send is in progress or its outcome is unknown; the draft must not change."""


class DuplicateDraft(StoreError):
    pass


class SendInProgress(StoreError):
    """Another active/succeeded/uncertain send exists for this recipient and campaign."""


@dataclass(frozen=True)
class StoredDraft:
    draft: Draft
    version: int
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class DraftMeta:
    """Provenance of a draft. Informational only: it never affects approval."""
    source_kind: str  # "template" or "imported"
    template_id: int | None = None
    template_name: str | None = None
    template_version: int | None = None
    source_file: str | None = None
    contact_id: str | None = None
    recipient_name: str | None = None
    notes: str | None = None


@dataclass(frozen=True)
class Event:
    id: int
    draft_id: str
    at: str
    kind: str
    actor: str | None
    detail: str | None
    fingerprint: str | None


@dataclass(frozen=True)
class SendAttempt:
    attempt_id: str
    draft_id: str
    campaign_id: str
    recipient: str
    fingerprint: str
    state: str
    started_at: str
    finished_at: str | None
    detail: str | None


def _norm(recipient: str) -> str:
    return recipient.strip().lower()


class DraftStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._read() as conn:  # executescript manages its own transactions
            conn.executescript(SCHEMA)

    # ---- connection handling -------------------------------------------------
    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = FULL")  # survive power loss / crashes
        return conn

    @contextmanager
    def _read(self) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        """A write transaction: all-or-nothing."""
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            else:
                conn.execute("COMMIT")
        finally:
            conn.close()

    # ---- helpers -------------------------------------------------------------
    @staticmethod
    def _to_stored(row: sqlite3.Row) -> StoredDraft:
        approval = None
        if row["approval_signature"]:
            approval = Approval(
                fingerprint=row["approval_fingerprint"],
                reviewer=row["approval_reviewer"],
                approved_at=row["approval_at"],
                signature=row["approval_signature"],
            )
        draft = Draft(
            recipient=row["recipient"],
            subject=row["subject"],
            body=row["body"],
            campaign_id=row["campaign_id"],
            draft_id=row["draft_id"],
            status=Status(row["status"]),  # unknown value -> ValueError (fail closed)
            approval=approval,
        )
        return StoredDraft(draft, row["version"], row["created_at"], row["updated_at"])

    @staticmethod
    def _add_event(conn, draft_id, kind, actor=None, detail=None, fingerprint=None) -> None:
        conn.execute(
            "INSERT INTO events (draft_id, at, kind, actor, detail, fingerprint) VALUES (?,?,?,?,?,?)",
            (draft_id, now_iso(), kind, actor, detail, fingerprint),
        )

    @staticmethod
    def _has_open_send(conn, draft_id: str) -> bool:
        row = conn.execute(
            "SELECT 1 FROM send_attempts WHERE draft_id=? AND state IN ('STARTED','UNCERTAIN')",
            (draft_id,),
        ).fetchone()
        return row is not None

    # ---- create / read -------------------------------------------------------
    def add(self, draft: Draft, actor: str = "system", meta: DraftMeta | None = None) -> StoredDraft:
        """Insert a brand-new draft. Raises DuplicateDraft if the person already has one in this campaign."""
        now = now_iso()
        if draft.status is not Status.DRAFT or draft.approval is not None:
            raise StoreError("Only fresh, unapproved drafts can be added")
        try:
            with self._tx() as conn:
                conn.execute(
                    "INSERT INTO drafts (draft_id, campaign_id, recipient, subject, body, status, version,"
                    " created_at, updated_at) VALUES (?,?,?,?,?,?,1,?,?)",
                    (draft.draft_id, draft.campaign_id, draft.recipient.strip(), draft.subject,
                     draft.body, draft.status.value, now, now),
                )
                self._add_event(conn, draft.draft_id, "CREATED", actor, fingerprint=draft.fingerprint)
                if meta is not None:
                    conn.execute(
                        "INSERT INTO draft_meta (draft_id, source_kind, template_id, template_name,"
                        " template_version, source_file, contact_id, recipient_name, notes)"
                        " VALUES (?,?,?,?,?,?,?,?,?)",
                        (draft.draft_id, meta.source_kind, meta.template_id, meta.template_name,
                         meta.template_version, meta.source_file, meta.contact_id,
                         meta.recipient_name, meta.notes),
                    )
        except sqlite3.IntegrityError as exc:
            raise DuplicateDraft(
                f"{draft.recipient} already has a draft in campaign {draft.campaign_id}"
            ) from exc
        return self.get(draft.draft_id)

    def get(self, draft_id: str) -> StoredDraft:
        with self._read() as conn:
            row = conn.execute("SELECT * FROM drafts WHERE draft_id=?", (draft_id,)).fetchone()
        if row is None:
            raise DraftNotFound(draft_id)
        return self._to_stored(row)

    def list(self, campaign_id: str | None = None, statuses: list[Status] | None = None) -> list[StoredDraft]:
        sql, params = "SELECT * FROM drafts WHERE 1=1", []
        if campaign_id:
            sql += " AND campaign_id=?"
            params.append(campaign_id)
        if statuses:
            sql += f" AND status IN ({','.join('?' * len(statuses))})"
            params.extend(s.value for s in statuses)
        sql += " ORDER BY created_at, recipient"
        with self._read() as conn:
            return [self._to_stored(r) for r in conn.execute(sql, params)]

    def get_meta(self, draft_id: str) -> DraftMeta | None:
        with self._read() as conn:
            row = conn.execute("SELECT * FROM draft_meta WHERE draft_id=?", (draft_id,)).fetchone()
        if row is None:
            return None
        data = dict(row)
        data.pop("draft_id")
        return DraftMeta(**data)

    def exists(self, campaign_id: str, recipient: str) -> bool:
        """True if this person already has a draft in the campaign (same rule as the unique index)."""
        with self._read() as conn:
            row = conn.execute(
                "SELECT 1 FROM drafts WHERE campaign_id=? AND lower(trim(recipient))=?",
                (campaign_id, _norm(recipient)),
            ).fetchone()
        return row is not None

    def recent_events(self, campaign_id: str | None = None, limit: int = 50) -> list[tuple[Event, str, str]]:
        """Newest events with (event, campaign_id, recipient), for the campaign activity overview."""
        sql = ("SELECT e.*, d.campaign_id AS _campaign, d.recipient AS _recipient FROM events e"
               " JOIN drafts d ON d.draft_id = e.draft_id")
        params: list = []
        if campaign_id:
            sql += " WHERE d.campaign_id=?"
            params.append(campaign_id)
        sql += " ORDER BY e.id DESC LIMIT ?"
        params.append(limit)
        out = []
        with self._read() as conn:
            for r in conn.execute(sql, params):
                data = dict(r)
                campaign, recipient = data.pop("_campaign"), data.pop("_recipient")
                out.append((Event(**data), campaign, recipient))
        return out

    def uncertain_counts(self) -> dict[str, int]:
        """{campaign_id: number of sends whose outcome is unknown}"""
        with self._read() as conn:
            return {r[0]: r[1] for r in conn.execute(
                "SELECT campaign_id, COUNT(*) FROM send_attempts WHERE state='UNCERTAIN' GROUP BY campaign_id")}

    def campaigns(self) -> list[str]:
        with self._read() as conn:
            return [r[0] for r in conn.execute("SELECT DISTINCT campaign_id FROM drafts ORDER BY 1")]

    def status_counts(self, campaign_id: str | None = None) -> dict[str, dict[str, int]]:
        """{campaign_id: {status: count}}"""
        sql = "SELECT campaign_id, status, COUNT(*) AS n FROM drafts"
        params: list = []
        if campaign_id:
            sql += " WHERE campaign_id=?"
            params.append(campaign_id)
        sql += " GROUP BY campaign_id, status"
        out: dict[str, dict[str, int]] = {}
        with self._read() as conn:
            for r in conn.execute(sql, params):
                out.setdefault(r["campaign_id"], {})[r["status"]] = r["n"]
        return out

    # ---- update --------------------------------------------------------------
    def save(self, draft: Draft, expected_version: int, actor: str,
             events: list[tuple[str, str | None]] | None = None) -> StoredDraft:
        """Persist changes made to a loaded draft.

        Refuses when: the draft changed meanwhile, it is already SENT, a send
        is open/uncertain, or the change tries to mark it SENT (only
        finish_send / resolve_attempt may do that).
        """
        with self._tx() as conn:
            row = conn.execute("SELECT * FROM drafts WHERE draft_id=?", (draft.draft_id,)).fetchone()
            if row is None:
                raise DraftNotFound(draft.draft_id)
            if row["version"] != expected_version:
                raise ConcurrentModification("The draft was changed elsewhere; reload and try again")
            if row["status"] == Status.SENT.value:
                raise StoreError("A sent draft is final and cannot be changed")
            if draft.status is Status.SENT:
                raise StoreError("Drafts can only become SENT through the send workflow")
            if self._has_open_send(conn, draft.draft_id):
                raise DraftLocked("A send is in progress or has an unknown outcome for this draft")
            a = draft.approval
            try:
                conn.execute(
                    "UPDATE drafts SET recipient=?, subject=?, body=?, status=?, version=version+1,"
                    " approval_fingerprint=?, approval_reviewer=?, approval_at=?, approval_signature=?,"
                    " updated_at=? WHERE draft_id=?",
                    (draft.recipient.strip(), draft.subject, draft.body, draft.status.value,
                     a.fingerprint if a else None, a.reviewer if a else None,
                     a.approved_at if a else None, a.signature if a else None,
                     now_iso(), draft.draft_id),
                )
            except sqlite3.IntegrityError as exc:
                raise DuplicateDraft(
                    f"{draft.recipient} already has a draft in campaign {draft.campaign_id}"
                ) from exc
            if row["status"] != draft.status.value:
                self._add_event(conn, draft.draft_id, "STATUS", actor,
                                f"{row['status']} -> {draft.status.value}")
            for kind, detail in events or []:
                fp = a.fingerprint if (a and kind == "APPROVED") else draft.fingerprint
                self._add_event(conn, draft.draft_id, kind, actor, detail, fp)
        return self.get(draft.draft_id)

    # ---- audit trail ---------------------------------------------------------
    def events(self, draft_id: str) -> list[Event]:
        with self._read() as conn:
            rows = conn.execute("SELECT * FROM events WHERE draft_id=? ORDER BY id", (draft_id,)).fetchall()
        return [Event(**dict(r)) for r in rows]

    # ---- sending -------------------------------------------------------------
    def begin_send(self, draft_id: str, expected_version: int) -> str:
        """Durably record "a send is starting" BEFORE anything is delivered.

        If the program dies after this point, the STARTED row survives the
        restart and is treated as an uncertain outcome (see service.recover_interrupted).
        """
        attempt_id = uuid.uuid4().hex
        try:
            with self._tx() as conn:
                row = conn.execute("SELECT * FROM drafts WHERE draft_id=?", (draft_id,)).fetchone()
                if row is None:
                    raise DraftNotFound(draft_id)
                if row["version"] != expected_version or row["status"] != Status.APPROVED.value:
                    raise ConcurrentModification("The draft changed or is no longer approved")
                stored = self._to_stored(row)
                conn.execute(
                    "INSERT INTO send_attempts (attempt_id, draft_id, campaign_id, recipient, fingerprint,"
                    " state, started_at) VALUES (?,?,?,?,?,'STARTED',?)",
                    (attempt_id, draft_id, row["campaign_id"], _norm(row["recipient"]),
                     stored.draft.fingerprint, now_iso()),
                )
                self._add_event(conn, draft_id, "SEND_STARTED", None, attempt_id, stored.draft.fingerprint)
        except sqlite3.IntegrityError as exc:
            raise SendInProgress(
                "A send to this recipient in this campaign is already in progress, done, or of unknown outcome"
            ) from exc
        return attempt_id

    def abort_send(self, attempt_id: str, detail: str) -> None:
        """The send was blocked before delivery: nothing left the building."""
        self._finish(attempt_id, "ABORTED", detail, new_status=None)

    def finish_send(self, attempt_id: str, success: bool, detail: str) -> None:
        self._finish(attempt_id, "SUCCEEDED" if success else "FAILED", detail,
                     new_status=Status.SENT if success else Status.FAILED)

    def resolve_attempt(self, attempt_id: str, actually_sent: bool, reviewer: str, note: str) -> None:
        """A human decides what really happened to an UNCERTAIN attempt."""
        self._finish(attempt_id, "SUCCEEDED" if actually_sent else "ABORTED",
                     f"resolved by {reviewer}: {note or 'no note'}",
                     new_status=Status.SENT if actually_sent else None,
                     actor=reviewer, required_state="UNCERTAIN")

    def mark_uncertain(self, attempt_id: str, detail: str) -> None:
        self._finish(attempt_id, "UNCERTAIN", detail, new_status=None, required_state="STARTED")

    def _finish(self, attempt_id: str, state: str, detail: str, new_status: Status | None,
                actor: str | None = None, required_state: str | None = None) -> None:
        with self._tx() as conn:
            att = conn.execute("SELECT * FROM send_attempts WHERE attempt_id=?", (attempt_id,)).fetchone()
            if att is None:
                raise StoreError(f"Unknown send attempt {attempt_id}")
            allowed = {required_state} if required_state else {"STARTED"}
            if att["state"] not in allowed:
                raise StoreError(f"Attempt is {att['state']}, expected {'/'.join(sorted(allowed))}")
            conn.execute(
                "UPDATE send_attempts SET state=?, finished_at=?, detail=? WHERE attempt_id=?",
                (state, now_iso(), detail, attempt_id),
            )
            if new_status is not None:
                conn.execute(
                    "UPDATE drafts SET status=?, version=version+1, updated_at=? WHERE draft_id=?",
                    (new_status.value, now_iso(), att["draft_id"]),
                )
            self._add_event(conn, att["draft_id"], f"SEND_{state}", actor, detail, att["fingerprint"])

    def attempts(self, draft_id: str | None = None, states: tuple[str, ...] | None = None) -> list[SendAttempt]:
        sql, params = "SELECT * FROM send_attempts WHERE 1=1", []
        if draft_id:
            sql += " AND draft_id=?"
            params.append(draft_id)
        if states:
            sql += f" AND state IN ({','.join('?' * len(states))})"
            params.extend(states)
        sql += " ORDER BY started_at"
        with self._read() as conn:
            return [SendAttempt(**dict(r)) for r in conn.execute(sql, params)]
