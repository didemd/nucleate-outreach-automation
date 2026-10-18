"""A small, versioned library of email templates.

Design notes (for beginners):
  * Templates live in the same local SQLite file as the drafts (data/outreach.db),
    which Git ignores. Only the fictional examples in the repo's templates/ folder
    are committed; they are copied into the library the first time it is opened.
  * Saving never overwrites. Every save adds a NEW VERSION, so a draft can always
    be traced back to the exact template text it was generated from.
  * Templates are plain text for humans (or an external AI chat) to use. Nothing
    here calls any AI service.
"""

from __future__ import annotations

import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from .contacts import Contact
from .drafts import now_iso
from .templating import _PLACEHOLDER, TemplateError, parse_template, render_email

MAX_TEMPLATE_BYTES = 50_000
ALLOWED_EXTENSIONS = (".txt", ".md", ".markdown")
# The values the generator can fill in (see templating.contact_values).
KNOWN_VARIABLES = ("name", "first_name", "institution", "research_area", "email", "sender_name")

_NAME_RE = re.compile(r"^[\w][\w .\-()]{0,79}$", re.UNICODE)

SCHEMA = """
CREATE TABLE IF NOT EXISTS templates (
    template_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    is_example INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_templates_name ON templates (lower(name));

CREATE TABLE IF NOT EXISTS template_versions (
    template_id INTEGER NOT NULL REFERENCES templates (template_id),
    version INTEGER NOT NULL,
    content TEXT NOT NULL,
    note TEXT,
    source_file TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (template_id, version)
);
"""


@dataclass(frozen=True)
class TemplateVersion:
    template_id: int
    name: str
    version: int
    content: str
    note: str | None
    source_file: str | None
    created_at: str
    is_example: bool = False


@dataclass(frozen=True)
class TemplateSummary:
    template_id: int
    name: str
    latest_version: int
    updated_at: str
    is_example: bool


def variables_in(text: str) -> list[str]:
    """Placeholder names used in a template, in order of first appearance."""
    seen: list[str] = []
    for match in _PLACEHOLDER.finditer(text):
        if match.group(1) not in seen:
            seen.append(match.group(1))
    return seen


def validate_template_text(text: str) -> list[str]:
    """Return a list of plain-language problems (empty list = the template is usable)."""
    problems: list[str] = []
    if "\x00" in text:
        problems.append("The file contains binary data, not plain text.")
        return problems
    if len(text.encode("utf-8")) > MAX_TEMPLATE_BYTES:
        problems.append(f"The template is longer than {MAX_TEMPLATE_BYTES // 1000} KB.")
    try:
        subject, body = parse_template(text)
        if not subject:
            problems.append("The 'Subject:' line is empty.")
        if not body.strip():
            problems.append("The template has no body text after the 'Subject:' line.")
    except TemplateError:
        problems.append("The first line must start with 'Subject:' (for example: Subject: Hello {{first_name}}).")
    unknown = [v for v in variables_in(text) if v not in KNOWN_VARIABLES]
    if unknown:
        problems.append(
            "Unknown variable(s): " + ", ".join("{{%s}}" % v for v in unknown)
            + ". Allowed: " + ", ".join("{{%s}}" % v for v in KNOWN_VARIABLES) + "."
        )
    return problems


MAX_SUBJECT_LENGTH = 200


def compose_template(subject: str, body: str) -> str:
    """Join separately typed subject and body into the stored 'Subject: ...' format.

    Raises TemplateError for a missing or multi-line subject, or an empty body.
    """
    if "\n" in subject or "\r" in subject:
        raise TemplateError("The subject must be a single line.")
    subject = subject.strip()
    if not subject:
        raise TemplateError("Please enter an email subject.")
    if len(subject) > MAX_SUBJECT_LENGTH:
        raise TemplateError(f"The subject is longer than {MAX_SUBJECT_LENGTH} characters.")
    if not body.strip():
        raise TemplateError("Please enter the email text.")
    return f"Subject: {subject}\n{body.replace(chr(13) + chr(10), chr(10)).strip(chr(10))}\n"


def decode_upload(filename: str, data: bytes) -> str:
    """Turn an uploaded TXT/Markdown file into text, or raise TemplateError with a friendly message."""
    if not filename.lower().endswith(ALLOWED_EXTENSIONS):
        raise TemplateError("Please upload a .txt or .md (Markdown) file.")
    if len(data) > MAX_TEMPLATE_BYTES:
        raise TemplateError(f"The file is larger than {MAX_TEMPLATE_BYTES // 1000} KB.")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise TemplateError("The file is not UTF-8 text. Save it as plain text (UTF-8) and try again.") from exc
    return text.replace("\r\n", "\n").replace("\r", "\n")


def clean_name(name: str) -> str:
    name = " ".join(name.split())
    if not _NAME_RE.match(name):
        raise TemplateError(
            "Give the template a short name (letters, numbers, spaces, - _ . and brackets; up to 80 characters)."
        )
    return name


class TemplateLibrary:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn:
            conn.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    # ---- reading -------------------------------------------------------------
    def list(self) -> list[TemplateSummary]:
        sql = ("SELECT t.template_id, t.name, t.is_example, MAX(v.version) AS latest, MAX(v.created_at) AS updated"
               " FROM templates t JOIN template_versions v USING (template_id)"
               " GROUP BY t.template_id ORDER BY t.is_example, lower(t.name)")
        with closing(self._connect()) as conn:
            return [TemplateSummary(r["template_id"], r["name"], r["latest"], r["updated"], bool(r["is_example"]))
                    for r in conn.execute(sql)]

    def get(self, template_id: int, version: int | None = None) -> TemplateVersion:
        with closing(self._connect()) as conn:
            if version is None:
                version = conn.execute("SELECT MAX(version) FROM template_versions WHERE template_id=?",
                                       (template_id,)).fetchone()[0]
            row = conn.execute(
                "SELECT t.name, t.is_example, v.* FROM template_versions v JOIN templates t USING (template_id)"
                " WHERE v.template_id=? AND v.version=?", (template_id, version)).fetchone()
        if row is None:
            raise TemplateError("That template version does not exist.")
        return TemplateVersion(row["template_id"], row["name"], row["version"], row["content"], row["note"],
                               row["source_file"], row["created_at"], bool(row["is_example"]))

    def versions(self, template_id: int) -> list[TemplateVersion]:
        with closing(self._connect()) as conn:
            nums = [r[0] for r in conn.execute(
                "SELECT version FROM template_versions WHERE template_id=? ORDER BY version DESC", (template_id,))]
        return [self.get(template_id, n) for n in nums]

    # ---- writing -------------------------------------------------------------
    def create(self, name: str, content: str, note: str = "", source_file: str | None = None,
               is_example: bool = False) -> TemplateVersion:
        """Add a brand-new template as version 1."""
        name = clean_name(name)
        self._require_valid(content)
        with closing(self._connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                cur = conn.execute("INSERT INTO templates (name, is_example, created_at) VALUES (?,?,?)",
                                   (name, int(is_example), now_iso()))
                tid = cur.lastrowid
                conn.execute("INSERT INTO template_versions VALUES (?,?,?,?,?,?)",
                             (tid, 1, content, note or None, source_file, now_iso()))
                conn.execute("COMMIT")
            except sqlite3.IntegrityError as exc:
                conn.execute("ROLLBACK")
                raise TemplateError(f"A template named '{name}' already exists.") from exc
            except BaseException:
                conn.execute("ROLLBACK")
                raise
        return self.get(tid, 1)

    def save_new_version(self, template_id: int, content: str, note: str = "",
                         source_file: str | None = None) -> TemplateVersion:
        """Add a new version; earlier versions are kept untouched."""
        self._require_valid(content)
        with closing(self._connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                latest = conn.execute("SELECT MAX(version) FROM template_versions WHERE template_id=?",
                                      (template_id,)).fetchone()[0]
                if latest is None:
                    raise TemplateError("That template does not exist.")
                conn.execute("INSERT INTO template_versions VALUES (?,?,?,?,?,?)",
                             (template_id, latest + 1, content, note or None, source_file, now_iso()))
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
        return self.get(template_id, latest + 1)

    def find_by_name(self, name: str) -> TemplateSummary | None:
        wanted = " ".join(name.split()).lower()
        return next((t for t in self.list() if t.name.lower() == wanted), None)

    @staticmethod
    def _require_valid(content: str) -> None:
        problems = validate_template_text(content)
        if problems:
            raise TemplateError(" ".join(problems))

    # ---- examples ------------------------------------------------------------
    def seed_examples(self, folder: Path) -> None:
        """Copy the repository's fictional example templates in, once. Never overwrites."""
        for file in sorted(folder.glob("*")):
            if file.suffix.lower() not in ALLOWED_EXTENSIONS:
                continue
            name = file.stem.replace("_", " ").capitalize() + " (example)"
            if self.find_by_name(name):
                continue
            try:
                self.create(name, decode_upload(file.name, file.read_bytes()), "Built-in fictional example",
                            source_file=file.name, is_example=True)
            except TemplateError:
                continue  # an invalid example file must never stop the app from starting


def preview_text(content: str) -> tuple[str, str]:
    """Fill a template with a fictional contact so people can see roughly what an email will look like."""
    demo = Contact("Dr. Alex Example", "Example University", "alex@example.org", "protein engineering", True)
    return render_email(content, demo, "Your Name")
