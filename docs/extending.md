# Extending the project

## Run the tests first
```bash
pytest
```
Add a test for every new behavior. Use fictional data only.

## Where new features go

| Goal | Where |
|---|---|
| Read Excel or Google Sheets | New loader in `contacts.py` (or a new module) that returns the same `LoadResult` / `Contact` objects |
| Generate text with Claude | New function producing a `Draft` (see `create_draft` in `drafts.py`); the result must still start as `DRAFT` and go through review |
| Send through Gmail | New subclass of `Sender` in `sender.py` implementing `_deliver()` only |
| Review interface (CLI or web) | Call `submit_for_review()`, then `ApprovalService.approve/reject` |

## Rules to keep
- Do not bypass `Sender.send()`: all approval and duplicate checks live there (`_check_allowed`).
- A real sender must implement only `_deliver()`, so those checks can't be skipped.
- Never commit real contacts, tokens, or keys. Put secrets in `.env`.
- Real sending must stay opt-in and clearly separated from the simulated sender.
