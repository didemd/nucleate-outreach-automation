# How the approval system works

## The idea in plain language

Before an email can be sent, a human must look at it and approve it. The approval is tied to the **exact text** they saw. If anyone changes the recipient, subject or body afterwards, the approval stops counting and the email must be reviewed again.

These rules are enforced by Python code, not by instructions to an AI.

## States

```
DRAFT ──> PENDING_REVIEW ──> APPROVED ──> SENT
              │                  │  └──> FAILED
              └──> REJECTED      │
   (REJECTED, FAILED, or any edit → back to DRAFT)
```

Only the transitions listed in `ALLOWED_TRANSITIONS` (`drafts.py`) are possible. `SENT` is final.

## The three safeguards

1. **Fingerprint.** `drafts.fingerprint()` computes a SHA-256 hash of recipient + subject + body. Any change, even one character, gives a different hash.
2. **Signature.** When a reviewer approves, `ApprovalService` stores the fingerprint and signs it (HMAC) with a secret key from `OUTREACH_APPROVAL_KEY`. Without the key, nobody can create a valid approval, so simply setting `status = APPROVED` by hand does not work.
3. **Check at the last moment.** `Sender.send()` re-verifies status, fingerprint and signature right before sending. Missing or unverifiable approval → `SendBlocked`.

## Preventing duplicates

- A draft that is `SENT` cannot be sent again.
- A ledger file (`data/sent_ledger.jsonl`, JSON lines) records every send. A recipient who already received a campaign is blocked, even from a different draft or after restarting the program.

## Editing

`draft.edit(...)` is the supported way to change content. It clears the approval and returns the draft to `DRAFT`. Editing by assigning `draft.body = ...` directly is also caught, because the fingerprint no longer matches.

## Known limits (Milestone 1)

- The signing key protects against accidents and casual tampering, not against someone with access to the key and the code. Keep the key secret and out of Git.
- Drafts are held in memory; persistent storage of drafts comes in a later milestone. The ledger is already persistent.
