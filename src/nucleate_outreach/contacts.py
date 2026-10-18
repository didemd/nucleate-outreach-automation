"""Load and validate contacts from CSV files."""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path

REQUIRED_FIELDS = ("name", "institution", "email", "research_area", "outreach_eligible")

_EMAIL_RE = re.compile(r"^[^@\s,;<>]+@[^@\s,;<>]+\.[^@\s,;<>]+$")
_TRUE = {"yes", "y", "true", "1"}
_FALSE = {"no", "n", "false", "0"}


@dataclass(frozen=True)
class Contact:
    name: str
    institution: str
    email: str  # always stored lowercase
    research_area: str
    outreach_eligible: bool

    @property
    def first_name(self) -> str:
        """Best-effort first name, skipping titles such as 'Dr.' or 'Prof.'."""
        titles = {"dr.", "dr", "prof.", "prof", "professor", "mr.", "ms.", "mrs."}
        parts = [p for p in self.name.split() if p.lower() not in titles]
        return parts[0] if parts else self.name


@dataclass(frozen=True)
class Issue:
    row: int  # row number in the file (header = row 1)
    message: str


@dataclass
class LoadResult:
    contacts: list[Contact] = field(default_factory=list)
    invalid: list[Issue] = field(default_factory=list)
    duplicates: list[Issue] = field(default_factory=list)
    warnings: list[Issue] = field(default_factory=list)

    @property
    def eligible(self) -> list[Contact]:
        return [c for c in self.contacts if c.outreach_eligible]


def is_valid_email(value: str) -> bool:
    return bool(_EMAIL_RE.match(value))


def _parse_bool(value: str) -> bool | None:
    v = value.strip().lower()
    if v in _TRUE:
        return True
    if v in _FALSE:
        return False
    return None


def load_contacts_csv(path: str | Path) -> LoadResult:
    """Read a CSV file and return valid contacts plus a report of problems.

    Bad rows never stop the import; they are listed in the result instead.
    The first occurrence of an email is kept; later ones are reported as duplicates.
    """
    result = LoadResult()
    seen_emails: dict[str, int] = {}
    seen_people: dict[tuple[str, str], int] = {}

    with open(path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        headers = [(h or "").strip().lower() for h in (reader.fieldnames or [])]
        missing = [f for f in REQUIRED_FIELDS if f not in headers]
        if missing:
            raise ValueError(f"CSV is missing required column(s): {', '.join(missing)}")
        reader.fieldnames = headers

        for row_number, raw in enumerate(reader, start=2):
            row = {k: (v or "").strip() for k, v in raw.items() if k}
            empty = [f for f in REQUIRED_FIELDS if not row.get(f)]
            if empty:
                result.invalid.append(Issue(row_number, f"missing value for: {', '.join(empty)}"))
                continue
            if not is_valid_email(row["email"]):
                result.invalid.append(Issue(row_number, f"invalid email address: {row['email']!r}"))
                continue
            eligible = _parse_bool(row["outreach_eligible"])
            if eligible is None:
                result.invalid.append(
                    Issue(row_number, f"outreach_eligible must be yes/no, got {row['outreach_eligible']!r}")
                )
                continue

            email = row["email"].lower()
            if email in seen_emails:
                result.duplicates.append(
                    Issue(row_number, f"duplicate email {email} (first seen in row {seen_emails[email]})")
                )
                continue
            seen_emails[email] = row_number

            person = (row["name"].lower(), row["institution"].lower())
            if person in seen_people:
                result.warnings.append(
                    Issue(row_number, f"same name and institution as row {seen_people[person]} but different email")
                )
            seen_people.setdefault(person, row_number)

            result.contacts.append(
                Contact(
                    name=row["name"],
                    institution=row["institution"],
                    email=email,
                    research_area=row["research_area"],
                    outreach_eligible=eligible,
                )
            )
    return result
