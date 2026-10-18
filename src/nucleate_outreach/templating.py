"""Deterministic placeholder replacement for email templates.

Template format: the first line is "Subject: ...", the rest is the body.
Placeholders look like {{name}}. A placeholder with no value is an error,
so a half-filled email can never be produced silently.
"""

from __future__ import annotations

import re
from pathlib import Path

from .contacts import Contact

_PLACEHOLDER = re.compile(r"\{\{\s*(\w+)\s*\}\}")


class TemplateError(ValueError):
    pass


def parse_template(text: str) -> tuple[str, str]:
    first, _, rest = text.partition("\n")
    if not first.lower().startswith("subject:"):
        raise TemplateError("Template must start with a 'Subject: ...' line")
    return first[len("subject:"):].strip(), rest.strip("\n")


def fill(text: str, values: dict[str, str]) -> str:
    def replace(match: re.Match) -> str:
        key = match.group(1)
        if key not in values or not str(values[key]).strip():
            raise TemplateError(f"No value for placeholder {{{{{key}}}}}")
        return str(values[key])

    return _PLACEHOLDER.sub(replace, text)


def contact_values(contact: Contact, sender_name: str) -> dict[str, str]:
    return {
        "name": contact.name,
        "first_name": contact.first_name,
        "institution": contact.institution,
        "research_area": contact.research_area,
        "email": contact.email,
        "sender_name": sender_name,
    }


def render_email(template_text: str, contact: Contact, sender_name: str) -> tuple[str, str]:
    """Return (subject, body) for one contact."""
    subject_t, body_t = parse_template(template_text)
    values = contact_values(contact, sender_name)
    subject = fill(subject_t, values)
    if "\n" in subject or "\r" in subject:
        raise TemplateError("Subject must be a single line")
    return subject, fill(body_t, values)


def load_template(path: str | Path) -> str:
    return Path(path).read_text(encoding="utf-8")
