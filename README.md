# synthdata-mail
Populate an empty, IMAP-accessible mailbox with coherent synthetic data — inbox/sent/drafts emails, contacts, and calendar events — for product demos and sandbox environments. Built for the Webmail 8 (WM8) rollout, but works against any standard IMAP mailbox.

Full technical specification: [`synthdata-mail-spec.md`](./synthdata-mail-spec.md). This README covers what the tool does and how to run it; the spec is the authoritative source for behavior, schemas, and design rationale.

## Why this exists

Demo/test webmail accounts provision empty. An empty inbox makes AI features (which need real content to act on) impossible to demonstrate, and it's a weak first impression for a client evaluating an upgrade. This tool generates a realistic-looking, internally consistent mailbox — the same synthetic people show up as email senders, calendar attendees, and contacts, not three disconnected piles of random data — so a demo account looks and behaves like one that's actually been in use.

## How it works (three stages)

1. **Generate content** (manual, outside this tool) — you run a documented prompt in Claude Code or Claude Cowork, which produces a single `dataset.json` file containing a persona, contacts, emails, and events, all cross-referenced. There's no API key requirement here — this step doesn't call any API from this tool, you just interact with Claude Code/Cowork directly.
2. **Turn that into files and mailbox content** (this tool) — validate the dataset, write `.vcf`/`.ics` files for manual import, and seed the mailbox directly over IMAP.
3. **Import contacts/calendar manually** — bulk-upload the generated `.vcf` and `.ics` files through the target webmail's own UI. This tool does not write to CalDAV/CardDAV (see spec §9).

Why the split: WM8 (and most webmail products) don't expose a bulk-import API for contacts/calendar, but they do support IMAP for mail. So mail gets seeded directly; contacts/calendar get generated as standard files you import by hand.

## Requirements

- Python 3.11+
- Dependencies: `imap_tools`, `vobject`, `icalendar`, `jsonschema`, `click`
- An IMAP-accessible mailbox to seed (server hostname, username, password)
- No Anthropic API key needed — content generation happens separately via Claude Code/Cowork, not through this tool

## Setup

```bash
git clone <repo-url>
cd synthdata-mail
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

`requirements.txt`:
```
imap_tools
vobject
icalendar
jsonschema
click
```

### Credentials file (recommended over interactive prompts for repeated use)

Create a file with restricted permissions:

```bash
touch ~/.synthdata-mail-creds
chmod 600 ~/.synthdata-mail-creds
```

Contents (flat `key=value`, one per line):

```
server=sync.megamailservers.com
username=demo@clientdomain.com
password=the-mailbox-password
```

The tool refuses to read this file if its permissions are looser than `600` — this is intentional (see spec §4, NFR-2), not a bug. If you'd rather not manage a file, omit `--creds-file` and the tool will prompt you interactively with hidden input instead.

**Never pass the password as a command-line flag.** There isn't one — this is deliberate (spec §6.1) since CLI arguments are visible in shell history and process listings.

## Usage

### 1. Generate a dataset

Run the content-generation prompt (see `prompts/generate-dataset.md` in this repo) through Claude Code or Cowork, specifying:
- Volume tier: `light` (~15 contacts / ~20 events / 50 emails), `medium` (~30 / ~50 / 100), or `heavy` (~50 / ~100 / 200)
- Business persona: e.g., "generic small business, mixed clients and vendors"

Save the output as `dataset.json`.

### 2. Validate it

```bash
python -m synthdata_mail validate --dataset dataset.json
```

Catches schema errors and dangling references (e.g., an email pointing to a contact that doesn't exist) before anything gets written or sent anywhere.

### 3. Generate contacts and calendar files

```bash
python -m synthdata_mail generate --dataset dataset.json --output-dir ./output/
```

Produces `output/contacts.vcf` and `output/events.ics`. Import both into the target webmail through its own UI (bulk import / add account features — see that product's documentation).

### 4. Seed the mailbox

```bash
python -m synthdata_mail seed \
  --dataset dataset.json \
  --server sync.megamailservers.com \
  --username demo@clientdomain.com \
  --creds-file ~/.synthdata-mail-creds
```

This connects over IMAP and appends every email in the dataset to the correct folder (inbox/sent/drafts) with realistic timestamps and read/unread state — throttled deliberately (see "A note on speed" below). Prints a `batch-id` at the end; **save this** if you plan to reset later.

**Optional: add a custom welcome email** that appears as the newest, unread item in the inbox:

```bash
python -m synthdata_mail seed \
  --dataset dataset.json \
  --server sync.megamailservers.com \
  --username demo@clientdomain.com \
  --creds-file ~/.synthdata-mail-creds \
  --custom-email welcome-email.json
```

`welcome-email.json`:
```json
{
  "subject": "Welcome to your Webmail 8 demo",
  "from_name": "Andres Rivera",
  "from_email": "andres@hostpapa.com",
  "html_file": "welcome-body.html"
}
```

`welcome-body.html` is a plain HTML file with the message content. A plain-text fallback is generated automatically.

### 5. Check what you've run

```bash
python -m synthdata_mail history
python -m synthdata_mail history --mailbox demo@clientdomain.com
```

Shows every past seed/reset run — timestamp, mailbox, batch-id, counts, status. Use this to find a `batch-id` if you didn't save it from step 4.

### 6. Reset a mailbox

Remove only what this tool added (recommended — leaves anything else in the account untouched):

```bash
python -m synthdata_mail reset \
  --server sync.megamailservers.com \
  --username demo@clientdomain.com \
  --creds-file ~/.synthdata-mail-creds \
  --batch-id <batch-id-from-seed-or-history>
```

Or wipe the mailbox entirely (irreversible — requires typed confirmation):

```bash
python -m synthdata_mail reset \
  --server sync.megamailservers.com \
  --username demo@clientdomain.com \
  --creds-file ~/.synthdata-mail-creds \
  --wipe-all
```

**Note**: reset only clears mailbox content (inbox/sent/drafts). Contacts and calendar entries imported in step 3 are not touched — remove those manually through the webmail UI if needed.

## A note on speed (please don't skip this)

The mail servers this tool talks to are shared infrastructure. Seeding runs deliberately slowly — a randomized delay between each message, with periodic longer pauses — to avoid looking like automated abuse to any monitoring on the server side. This is intentional, not a performance bug. Don't try to speed it up by lowering `--delay-min`/`--delay-max` unless you understand the risk of the target account being rate-limited or flagged. Defaults and rationale: spec §4, NFR-1.

## What this tool does not do

- Does not write to CalDAV/CardDAV — contacts and calendar events are file-based, manual import only.
- Does not send email externally — all mailbox content is injected directly via IMAP, nothing is relayed or delivered anywhere.
- Does not call any AI API — content generation (step 1) is a separate manual step you run yourself in Claude Code/Cowork.
- Does not support concurrent use by multiple people against the same mailbox at once.

Full list with rationale: spec §9 (Out of Scope).

## Troubleshooting

- **"Credentials file permissions rejected"** — run `chmod 600 <path>` on your credentials file.
- **"Folder not found" during seed** — the tool looks for Sent/Drafts via standard IMAP conventions first, then common literal names. If your target server uses a different sent/drafts naming convention, check its actual folder list (any IMAP-capable mail client will show this) and let the maintainer know — this may need a config addition.
- **Seed reports partial success** — some messages succeeded, some didn't (connection hiccup, server rejection). Check the printed per-message failure details; already-succeeded messages remain in the mailbox, nothing is rolled back automatically.
- **Want to redo a demo from scratch** — `reset --batch-id <id>` then `seed` again with a fresh (or the same) `dataset.json`.

## Project structure (suggested)

```
synthdata-mail/
├── synthdata_mail/          # tool source
├── prompts/
│   └── generate-dataset.md  # Stage 0 prompt template for Claude Code/Cowork
├── test/
│   └── fixtures/            # sample dataset.json files, valid and invalid
├── requirements.txt
├── README.md                # this file
└── synthdata-mail-spec.md   # full specification
```
