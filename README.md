# nucleate-outreach-automation

A reproducible, AI-assisted email outreach system for Nucleate Germany (Activator Program), built around **mandatory human approval**.

> **Status: Milestone 2 (persistent drafts + local review dashboard).** Everything is simulated. The code does **not** connect to Gmail, Claude, or any other service, and cannot send real email. The dashboard is a **single-user, local-only prototype**, not a shared or deployed application.

## What it does today

1. Imports contacts from a CSV file and validates them (required fields, email format, duplicates).
2. Builds personalized drafts from a template using plain placeholder replacement.
3. Forces every draft through a review workflow: `DRAFT → PENDING_REVIEW → APPROVED → SENT` (plus `REJECTED` and `FAILED`).
4. "Sends" only through a simulated sender that checks approvals and records results in a local ledger.
5. **(Milestone 2)** Stores drafts, approvals, an audit trail and send attempts in a local SQLite database that survives restarts.
6. **(Milestone 2)** Offers a Streamlit dashboard to filter, read, edit, approve or reject drafts, test simulated sending, and watch campaign progress.
7. **(Dashboard redesign)** Five beginner-friendly tabs — **Emails, Import, Templates, Campaigns, Settings**: a click-a-row review queue, import of contact lists (with a versioned template library) or of complete drafts from CSV/XLSX, and an always-visible sending-account box ("Not connected — simulated sending only"). See the **[user guide](docs/dashboard-guide.md)**.

## Quick start

```bash
git clone https://github.com/didemd/nucleate-outreach-automation.git
cd nucleate-outreach-automation
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev,dashboard]"
python -m nucleate_outreach.demo # safe demo, fictional data
pytest                           # run the automated tests

nucleate-dashboard init-key      # one time: creates a private approval key in .env
nucleate-dashboard               # starts the dashboard at http://127.0.0.1:8501
```

Requires Python 3.10 or newer. The core (Milestone 1) has no dependencies; the dashboard needs `streamlit` and `openpyxl` (for Excel import), both installed by `.[dashboard]`.

## Folder guide

| Path | Purpose |
|---|---|
| `src/nucleate_outreach/` | The program code (see below) |
| `tests/` | Automated tests; `tests/fixtures/` holds fictional CSV data |
| `docs/` | Longer documentation ([dashboard guide](docs/dashboard-guide.md), [approval system](docs/approval-system.md), [extending](docs/extending.md)) |
| `config/` | Campaign settings (`campaign.example.json`) |
| `templates/` | Reusable email templates with `{{placeholders}}` |
| `examples/` | Fictional example contacts |
| `data/` | Local database (`outreach.db`) and ledger. Git-ignored; never committed |
| `.env.example` | Shows which secrets exist. Copy to `.env` (git-ignored) |
| `pyproject.toml` | Python project and dependency configuration |

Code modules in `src/nucleate_outreach/`:

- `contacts.py` – CSV import, validation, duplicate detection
- `templating.py` – placeholder replacement
- `drafts.py` – the `Draft` object, its states, and the content fingerprint
- `approval.py` – the only code that can create or verify an approval
- `sender.py` – sender base class (all safety checks) and `SimulatedSender`
- `demo.py` – the guided demonstration
- `settings.py` – data folder and approval-key lookup (environment or `.env`)
- `store.py` – SQLite storage; the database itself enforces key safety rules
- `service.py` – `ReviewService`, the only entry point the dashboard uses (all rules live here)
- `template_library.py` – versioned template library (stored in the local database, outside Git)
- `draft_import.py` – validates and reads complete drafts from CSV/XLSX (never accepts status or approvals)
- `sender_identity.py` – the (currently always "not connected") sending-account description
- `dashboard/app.py` – page layout; one module per tab (`emails.py`, `import_tab.py`, `templates_tab.py`, `campaigns.py`, `settings_tab.py`); `view.py` holds the plain-language wording
- `launch.py` – the `nucleate-dashboard` command

## Security and privacy

This repository is public. **Never commit** real contact lists, credentials, OAuth tokens or API keys. `.gitignore` blocks `.env`, `data/`, all `*.csv` (except the fictional example and test fixtures), Excel files, and credential/token JSON files. Use only fictional data in tests and examples.

See [docs/approval-system.md](docs/approval-system.md) and [docs/extending.md](docs/extending.md) for more.
