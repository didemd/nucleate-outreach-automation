# nucleate-outreach-automation

A reproducible, AI-assisted email outreach system for Nucleate Germany (Activator Program), built around **mandatory human approval**.

> **Status: Milestone 1 (foundation).** Everything is simulated. The code does **not** connect to Gmail, Claude, or any other service, and cannot send real email.

## What it does today

1. Imports contacts from a CSV file and validates them (required fields, email format, duplicates).
2. Builds personalized drafts from a template using plain placeholder replacement.
3. Forces every draft through a review workflow: `DRAFT → PENDING_REVIEW → APPROVED → SENT` (plus `REJECTED` and `FAILED`).
4. "Sends" only through a simulated sender that checks approvals and records results in a local ledger.

## Quick start

```bash
git clone https://github.com/didemd/nucleate-outreach-automation.git
cd nucleate-outreach-automation
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
python -m nucleate_outreach.demo # safe demo, fictional data
pytest                           # run the automated tests
```

Requires Python 3.10 or newer. No runtime dependencies.

## Folder guide

| Path | Purpose |
|---|---|
| `src/nucleate_outreach/` | The program code (see below) |
| `tests/` | Automated tests; `tests/fixtures/` holds fictional CSV data |
| `docs/` | Longer documentation ([approval system](docs/approval-system.md), [extending](docs/extending.md)) |
| `config/` | Campaign settings (`campaign.example.json`) |
| `templates/` | Reusable email templates with `{{placeholders}}` |
| `examples/` | Fictional example contacts |
| `data/` | Local run output (ledger). Git-ignored; never committed |
| `.env.example` | Shows which secrets exist. Copy to `.env` (git-ignored) |
| `pyproject.toml` | Python project and dependency configuration |

Code modules in `src/nucleate_outreach/`:

- `contacts.py` – CSV import, validation, duplicate detection
- `templating.py` – placeholder replacement
- `drafts.py` – the `Draft` object, its states, and the content fingerprint
- `approval.py` – the only code that can create or verify an approval
- `sender.py` – sender base class (all safety checks) and `SimulatedSender`
- `demo.py` – the guided demonstration

## Security and privacy

This repository is public. **Never commit** real contact lists, credentials, OAuth tokens or API keys. `.gitignore` blocks `.env`, `data/`, all `*.csv` (except the fictional example and test fixtures), Excel files, and credential/token JSON files. Use only fictional data in tests and examples.

See [docs/approval-system.md](docs/approval-system.md) and [docs/extending.md](docs/extending.md) for more.
