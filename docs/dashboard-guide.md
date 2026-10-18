# Nucleate Outreach — user guide

This app helps you prepare outreach emails and have a person check every one of them before anything could be sent.

> **Nothing is ever sent.** Sending is *simulated*. The app is not connected to Gmail or any other email account.
> It runs **only on your own computer** and is meant for **one person at a time**. Do not put it on a server and do not share it.

*Tip for screenshots: each section below says which part of the screen to capture.*

---

## 1. Install it (once)

You need Python 3.10 or newer. Open a terminal and run:

```bash
git clone https://github.com/didemd/nucleate-outreach-automation.git
cd nucleate-outreach-automation
python3 -m venv .venv
source .venv/bin/activate              # Windows: .venv\Scripts\activate
pip install -e ".[dev,dashboard]"
nucleate-dashboard init-key            # creates your private approval key (stored in the hidden file .env)
```

**What is the approval key?** A secret that is used to "stamp" every approval, so an approval cannot be faked or carried over to a different text. It stays on your computer in `.env` (never shared, never uploaded to GitHub). Without it the app still opens, but you can only look — **Approve** stays switched off.

## 2. Start it

```bash
cd nucleate-outreach-automation
source .venv/bin/activate
nucleate-dashboard
```

Your browser opens at **http://127.0.0.1:8501**. (`127.0.0.1` means "this computer only".) To stop, press `Ctrl+C` in the terminal. Your work is saved in `data/outreach.db`, so it is still there next time.

## 3. The screen

📸 *Screenshot: the whole top of the page.*

- **Sending account** (top box, always visible): says **"Not connected — simulated sending only."** Nobody can type a sender address here. When a real account is connected in the future, its verified address will appear in this box.
- Five tabs: **Emails · Import · Templates · Campaigns · Settings**.

Why is there no "your name" box? This is a single-person local prototype, so every decision is recorded as **"Local operator (unverified)"**. That is a label, *not* a login — the app cannot tell who you are.

## 4. Typical workflow

1. **Templates** — check or add the email text you want to use.
2. **Import** — add people (with a template) *or* add finished emails.
3. **Emails** — read each email and approve, edit or reject it.
4. **Campaigns** — see the numbers; try a simulated send.

## 5. Import tab

📸 *Screenshot: the Import tab with the preview showing.*

Choose one of two ways:

### A. Contact list + a template
1. Use the example list or upload your own CSV (columns: `name, institution, email, research_area, outreach_eligible`). Use **Download an example contact file** to see the format.
2. Pick a **template** and give the campaign a **name**. The "signature name" is just the text printed at the end of each email.
3. Read the preview of the first email, then press **Create emails**.

Each email remembers which template and version it was made from.

### B. Complete email drafts
For emails you wrote elsewhere (ChatGPT, Claude Chat, by hand).

1. Press **Download example (CSV)** or **(Excel)** and copy the layout. One row per email:

   | Column | Needed? | Meaning |
   |---|---|---|
   | `campaign` | yes (or fill in the default campaign box) | campaign name |
   | `recipient_email` | yes | who it is for |
   | `subject` | yes | one line |
   | `body` | yes | the whole email; line breaks and umlauts are fine |
   | `contact_id`, `recipient_name`, `personalization_notes` | optional | for your own reference |

2. Upload the file. The app **checks it first** and shows: how many emails are ready, which are already in the app, and which rows have problems (with the row number and the reason). Nothing is saved yet.
3. Read any email in full with *Read a full email before importing*.
4. Press **Import N email(s) for review**. Rows with problems are skipped.

Good to know:
- Subject and text are saved **exactly as written**.
- A column called *status*, *approved*, *signature* and so on is **ignored**. Every imported email starts as **Pending review** and must be approved by a person.
- Importing the same file twice does nothing the second time: a person can only have one email per campaign.

## 6. Templates tab

📸 *Screenshot: a template with the preview box.*

- **Create a new template** (no file needed): open **📝 Create new template**, type a **name**, an **email subject** and paste or type the **email text**. Use variables like `{{name}}` where the person's details should go. A **preview** (filled in with a fictional person) appears as you type. Problems — an empty field, a subject on more than one line, an unknown variable, a name already in use — are explained in red and keep **Save template** switched off. Saving stores it as **version 1**, and it appears straight away in the Import tab's template list.
- **Add a template from a file**: open "Add a template from a file", upload a `.txt` or `.md` file, check the preview, give it a name, and save. The first line must be `Subject: …`. You can use these variables: `{{name}}`, `{{first_name}}`, `{{institution}}`, `{{research_area}}`, `{{email}}`, `{{sender_name}}`. Files with other variables, no subject line, or binary content are refused with an explanation.
- **View / preview**: pick a template and a version. The toggle fills it with a fictional person so you can see how it will look.
- **Copy**: use the small copy icon in the top-right corner of the text box.
- **Download**: the *Download this version* button.
- **Edit**: open *Edit and save as a new version*. Earlier versions are never overwritten; the new text becomes version 2, 3 and so on, and *Version* lets you look at any older one.
- Templates are stored on your computer only (`data/outreach.db`). The built-in "(example)" templates are fictional.

## 7. Emails tab

📸 *Screenshot: the table with one row selected and the details underneath.*

1. Use **Campaign** and **Status** to narrow the list.
2. **Click a row.** The full email opens below the table: sender, recipient, subject, text, status, who decided what and when, and where the email came from.
3. Choose an action:
   - **✅ Approve** — you approve *exactly the text on screen*. If the email was changed after you opened it, approval is refused.
   - **⛔ Reject** — optionally type a reason first.
   - **✏️ Edit** — change recipient, subject or text. **Any change cancels an existing approval** and turns the email back into a *Draft*; press **Submit for review** to put it in the queue again.
4. The email you are working on **stays open** after each action, even if the filter would now hide it.

Status words: **Draft** → **Pending review** → **Approved** → **Simulated sent**. Also **Rejected** and **Failed**.

## 8. Campaigns tab

📸 *Screenshot: the six number boxes.*

For one campaign or all of them: **Total drafts · Pending review · Approved · Rejected · Simulated sent · Failed or uncertain**, a table per campaign, and a *Recent activity* list you can filter.

At the bottom, **Simulated sending** tries every approved email. Only approved emails are touched, and a person is never "sent" the same campaign twice. If the program is closed in the middle of a simulated send, the outcome is *unknown*: the email shows under **Needs a human decision**, and you say whether it was delivered or not.

## 9. Settings tab

Shows (read-only): local prototype mode, simulation-only, Gmail connection (*Not connected*), whether the approval key is available (never the key itself), and where the database file is.

## 10. Troubleshooting

| What you see | What to do |
|---|---|
| **Approve** is greyed out | The approval key is missing. Run `nucleate-dashboard init-key`, then restart. |
| "No emails match these filters" | Clear the Campaign / Status filters, or import something. |
| A CSV with umlauts looks wrong | In Excel, save as **CSV UTF-8**. |
| `command not found: nucleate-dashboard` | Activate the environment first: `source .venv/bin/activate`. |
| Port already in use | `nucleate-dashboard --server.port 8502` |

## 11. For developers

```bash
pytest          # all tests; they use temporary databases and fictional data only
```

| Part | Why |
|---|---|
| **SQLite** | One file, crash-safe, no server. |
| **`ReviewService` between screen and database** | Buttons are only convenience: every rule (valid approval, no editing sent mail, no duplicates) is re-checked in the backend. |
| **Approval signature over a fingerprint** | Any change to recipient, subject or text invalidates the approval. |
| **Database-level rules** | A unique index allows one active send per person per campaign; `APPROVED` requires a signature. |
| **"Record before you send"** | `SEND_STARTED` is saved before delivery, so a crash leaves evidence; uncertain outcomes stay blocked until a human decides. |
| **Provenance in a separate table** (`draft_meta`) | Template version / import file are informational and cannot affect approval. |
| **Template library in the same local DB** | Versioned, private, outside Git. |

### Known limitations
- No login: "Local operator" is a label. Anyone with access to your computer account can use the app and read `.env`.
- Someone holding both `data/outreach.db` **and** the key could forge approvals. Keep both private.
- Only the simulated sender exists: no Gmail, Google Workspace sign-in or AI integration.
- Contacts are not stored separately; they become emails at import time.
- Templates can be added and versioned, not deleted.
