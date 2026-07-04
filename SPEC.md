# synthdata-mail — Specification

## 1. Overview

### Problem Statement

IMAP-accessible mailbox accounts used for product demos and sandbox environments — such as Webmail 8 (WM8) test accounts — typically provision empty: no inbox, sent, drafts, contacts, or calendar data. This undermines two things simultaneously: business clients evaluating a product for upgrade approval cannot meaningfully assess it in an empty account, and AI features that depend on populated data to function cannot be demonstrated at all in this state. The operator currently has no tool to populate demo accounts, forcing either a poor "empty box" demo experience or manual, ad-hoc data entry that doesn't scale across multiple demos.

This tool is general-purpose — it works against any mailbox reachable via standard IMAP — with the WM8 rollout as its motivating first use case, not a hard dependency.

### Goals

- Generate a coherent, cross-referenced synthetic dataset — contacts, emails (inbox/sent/drafts), and calendar events — where entities reference each other realistically (the same synthetic contacts appear as email senders/recipients and calendar attendees), rather than independently randomized data that fails to hold together under inspection.
- Populate a target mailbox's inbox/sent/drafts folders directly via IMAP, without requiring SMTP relay or external mail delivery.
- Produce `.vcf` (contacts) and `.ics` (calendar events) files for manual bulk import through the target webmail's UI, since bulk-import APIs and CalDAV/CardDAV write access are not assumed available.
- Support a custom, operator-authored HTML email (with specified sender name/address) that appears as the most recent inbox item, distinct from the synthetic dataset.
- Support both selective removal (only what this tool created) and full mailbox wipe, so demo accounts can be reset and reseeded across multiple engagements without manual cleanup.
- Operate within shared-infrastructure constraints — throttled, non-parallel IMAP access that does not trigger abuse/rate-limit detection on the mail cluster.
- Maintain a local run history (mailbox, timestamp, action, batch ID, item counts) so past runs can be identified and referenced for reset operations.

### Success Criteria

- Given a volume tier (light/medium/heavy) and a business persona, the tool produces a mailbox populated with realistic, internally-consistent email threads, a `.vcf` file of matching contacts, and an `.ics` file of matching calendar events, in under one operator session (single command per stage).
- A generated dataset shows zero dangling references — every contact referenced by an email or event resolves to an actual entry in the generated contact list.
- Seeding a "light" tier account completes without triggering any observable rate-limiting, connection drop, or account restriction on the shared mail cluster.
- An operator can selectively reset a previously seeded mailbox (removing only tool-created content) and reseed it, with the custom welcome email correctly cleared and recreated as part of that cycle.
- Two different LLMs implementing this spec independently produce tools with equivalent CLI surface, equivalent file outputs (schema-compatible `.vcf`/`.ics`/log format), and equivalent IMAP behavior (folder targeting, flags, throttling), even though internal code structure may differ.

### Non-Goals (summary — full detail in §9 Out of Scope)

Contacts and calendar events are written to files for manual import; this tool does not write to the target mailbox's CalDAV/CardDAV service. Mailbox reset covers only IMAP-seeded content; contacts/calendar removal remains a manual UI operation.

---

## 2. Architecture

### System Overview

This is a two-part system with a hard boundary between them: an **external, manual content-generation step** (performed by the operator via Claude Code/Cowork, no API integration) and a **deterministic local CLI** that consumes that content and performs all file writes and IMAP operations. No component of the CLI calls an LLM at runtime.

```
┌─────────────────────────────┐         ┌──────────────────────────────────────┐
│  STAGE 0: Content Generation │         │            DETERMINISTIC CLI          │
│  (manual, outside this tool) │         │                                        │
│                               │ writes  │  ┌────────────┐                       │
│  Operator runs a documented   │────────▶│  │  Schema     │  dataset.json         │
│  prompt in Claude Code,       │         │  │  Validator  │─────────────┐         │
│  producing dataset.json       │         │  └────────────┘              │         │
│  (contacts, emails, events,   │         │        │ fail: abort,        │         │
│  all foreign-keyed to a       │         │        │ report errors       ▼         │
│  shared persona/contact list) │         │        ▼               ┌──────────┐    │
└─────────────────────────────┘         │   valid dataset ────────▶│ Writers  │    │
                                          │                          └────┬─────┘    │
                                          │              ┌────────────────┼───────┐ │
                                          │              ▼                ▼       ▼ │
                                          │        vCard Writer    iCal Writer  IMAP│
                                          │        (contacts.vcf)  (events.ics) Seed│
                                          │                                     Client│
                                          │                                        │ │
                                          │                                        ▼ │
                                          │                                  Target Mailbox
                                          │                                  (INBOX/Sent/
                                          │                                   Drafts, via
                                          │                                   IMAP APPEND,
                                          │                                   throttled)
                                          └──────────────────────────────────────┘
                                                       │
                                                       ▼
                                            history.jsonl (append-only log)
```

### Components

**1. Content Generation (Stage 0, external to this codebase)**
Not implemented as code. This spec includes a documented prompt template (delivered separately) that the operator runs manually in Claude Code, supplying volume tier and business persona as parameters. Output is a single `dataset.json` file conforming to the schema in §5. This stage is re-run whenever the operator wants a fresh dataset; it has no dependency on the CLI and vice versa.

**2. Schema Validator**
First stage of the CLI proper. Loads `dataset.json`, validates structure against the JSON Schema (§5), then performs referential integrity checks beyond what JSON Schema alone can express: every `contact_id` referenced by an email or event must exist in the `contacts` array. Fails loud (non-zero exit, explicit list of dangling references) rather than silently dropping or ignoring bad references. This is a hard gate — no writer runs on unvalidated data.

**3. vCard Writer**
Converts `dataset.json` contacts into a single `.vcf` file (multiple vCard entries, one file) using `vobject`. Output path is operator-specified or defaulted to a local `./output/` directory. No network activity — pure file generation for manual UI import.

**4. iCalendar Writer**
Converts `dataset.json` events into a single `.ics` file (multiple `VEVENT` entries) using the `icalendar` library, with attendees resolved from the same contact list. Same manual-import model as contacts.

**5. IMAP Seed Client**
The only component that touches the network. Responsibilities:
- Connect via IMAP over SSL/TLS using operator-supplied server/credentials (prompted interactively or read from a restricted-permission credentials file — never passed as CLI arguments; see §4 NFRs).
- For each email in `dataset.json`, construct an RFC 822 message (via Python's `email` module) and `APPEND` it to the correct folder (INBOX, Sent, or Drafts per the email's designated folder) using `imap_tools`, setting internal date and flags (`\Seen`/unset) per the dataset.
- Tag every appended message with a custom header, `X-WM8-Seed-Batch: <batch-id>`, where `batch-id` is a UUID generated once per seed run. (Header name retained from original development for stability; not tied to WM8 specifically.)
- If a custom email is supplied (`--custom-email`), construct it as a separate HTML message per §3 with an internal date newer than all other messages in the batch, tag it with the same batch header, and append it to INBOX.
- Enforce throttling between every APPEND call (§4 NFRs) — this is not an optional wrapper, it's integral to this component's control flow.
- On per-message failure (auth drop, connection reset, server error), log the failure and continue with remaining messages rather than aborting the batch; report a full success/failure breakdown at the end.

**6. Reset Client**
Separate operation, same IMAP connection primitives as the Seed Client. Given a `batch-id` (supplied directly or looked up via History), performs `SEARCH HEADER X-WM8-Seed-Batch <batch-id>` per folder, then `UID STORE +FLAGS.SILENT (\Deleted)` and `UID EXPUNGE` on the matching set. Supports a `--wipe-all` mode that instead does an unscoped `SEARCH ALL` / flag / expunge per folder, gated behind an explicit confirmation prompt. Does not touch contacts or calendar data (out of scope, §9).

**7. History Logger**
Appends one JSON line per CLI invocation (seed/reset) to `history.jsonl`, per the schema in §5. Never writes credentials. Read path (`history` command) filters by mailbox and formats for terminal display.

### Data Flow Summary

`dataset.json` (hand-off artifact from Stage 0) → Validator → {vCard Writer, iCalendar Writer, IMAP Seed Client} run independently off the same validated dataset → History Logger records the outcome of whichever stage ran. Reset is a separate flow that does not depend on `dataset.json` at all — it operates purely on the batch tag already present in the mailbox.

### Key Architectural Decisions (with rationale)

- **No AI at runtime**: keeps the CLI deterministic, testable without model access, and reusable independent of which LLM/tool produced the dataset.
- **IMAP APPEND, not SMTP relay**: avoids external delivery dependency, permits arbitrary internal dates/flags/headers, and confines all "spoofed" sender behavior (custom email's From header) to direct mailbox injection rather than anything that transits a mail-relay's authentication checks.
- **Manual UI import for contacts/calendar**: general assumption is that bulk-import APIs and CalDAV/CardDAV write access are not available; building that transport was evaluated and explicitly descoped (§9).
- **Batch tagging via custom header**: the single mechanism that makes selective reset, partial-failure reporting, and history lookups all work off the same identifier.
- **Folder targeting is server-agnostic by default**: since this tool is not WM8-specific, folder resolution defaults to IMAP special-use attributes (`\Sent`, `\Drafts`) with literal-name fallback, rather than assuming any one server's literal folder names (see §6.2 and §10 item 2 for the WM8-specific literal names as a confirmed fallback case).

---

## 3. Functional Requirements

### FR-1: Dataset Validation (`validate` command)

**Input**: path to `dataset.json`.

**Behavior**:
- Validates structure against the JSON Schema (§5).
- Performs referential integrity checks: every `contact_id` in `emails[]` and every entry in `attendee_contact_ids[]` in `events[]` must resolve to an entry in `contacts[]`.
- On success: prints a summary (contact/email/event counts) and exits 0.
- On failure: prints every schema violation and every dangling reference found (not just the first), exits non-zero. Does not partially proceed.

**Output**: none (validation-only; no files written, no network activity).

This command can be run standalone or is invoked automatically as the first step of `generate` and `seed`.

---

### FR-2: File Generation (`generate` command)

**Input**: validated `dataset.json`; optional `--output-dir` (default `./output/`).

**Behavior**:
- Runs FR-1 validation first; aborts on failure.
- Writes `contacts.vcf` — one vCard entry per contact, using `vobject`.
- Writes `events.ics` — one `VEVENT` per event, attendees resolved from `contacts[]` by `contact_id`, using `icalendar`.

**Output**: `<output-dir>/contacts.vcf`, `<output-dir>/events.ics`. No network activity. Idempotent — re-running overwrites prior output files without side effects elsewhere.

**Note**: this command does not write emails anywhere. Email content lives only in `dataset.json` and is consumed exclusively by `seed` (FR-3), since there is no file-based import path for mail.

---

### FR-2a: Date Distribution Requirements (Generation Constraint)

Applies to Stage 0 content generation (the prompt template), not the deterministic CLI, which validates structure but does not resample or verify date distribution beyond schema type-correctness.

- **Emails**: timestamps must be past-only relative to generation time. Lookback window: 90 days for light/medium tiers, 180 days for heavy tier (avoids unrealistic density from packing 200 emails into the same 90-day window used for 50). Distribution should skew recent — more messages in the last 2–3 weeks, tapering off further back — matching how an actively-used inbox looks.
- **Events**: timestamps span both past and future, asymmetric window: 30 days back to 60 days forward from generation time, slightly favoring upcoming events since a demo benefits more from showing "what's coming up" than a deep backlog.
- **Rationale for the asymmetry**: a received or sent email is inherently a past occurrence — a future-dated email doesn't make logical sense. A calendar populated with only past events looks abandoned. This asymmetry is deliberate.

---

### FR-3: Mailbox Seeding (`seed` command)

**Input**: validated `dataset.json`; IMAP connection details (server host, username — see §4 for credential handling, password never as a CLI argument); optional `--custom-email <path-to-json>` (schema in §5); optional `--batch-id` (auto-generated UUID if omitted).

**Behavior**:
1. Runs FR-1 validation first; aborts on failure.
2. Opens one IMAP connection (SSL/TLS). No parallel connections.
3. For each email in `dataset.json.emails[]`, in the order listed:
   - Constructs an RFC 822 `multipart/alternative` message (From/To resolved from `contact_id` via `contacts[]`, subject, threading headers if present in the dataset). Both parts are generated from the dataset's `body` field:
     - **HTML part**: the body text is wrapped in a minimal HTML email template and followed by a signature block. For `incoming` messages the signature is derived from the contact's `full_name`, `company`, `role`, `email`, and `phone` fields. For `outgoing` messages the signature uses the dataset's `persona.business_name` and `persona.business_type`.
     - **Plain-text part**: the unmodified body text followed by a text-formatted version of the same signature, separated by `--`.
   - Sets internal date from the dataset's specified timestamp; sets `\Seen` flag per the dataset's `read` boolean.
   - Tags the message with header `X-WM8-Seed-Batch: <batch-id>`.
   - `APPEND`s to the folder specified per-message (`inbox` | `sent` | `drafts`), resolved per §6.2's folder-targeting contract.
   - Applies the throttling delay (§4) before the next APPEND.
   - On failure for this message: logs the failure (message index, error), continues to the next message. Does not abort the batch.
4. If `--custom-email` is supplied:
   - Loads the JSON descriptor (subject, from_name, from_email, html_file path).
   - Constructs a `multipart/alternative` HTML message with the specified sender fields, with a plain-text fallback part auto-derived from the HTML body via tag-stripping.
   - Sets internal date to the latest timestamp in the batch (i.e., `max(all message dates) + 1 second`), ensuring it sorts first in a newest-first inbox view.
   - Sets `\Seen` unset (appears unread).
   - Tags with the same `X-WM8-Seed-Batch` header as the rest of the batch.
   - Appends to INBOX. Same per-message failure handling as step 3.
5. On completion: prints a summary — total attempted, succeeded, failed (with reasons) — and records the run via the History Logger (FR-5).

**Output**: mailbox state changes (no local files). Exit code reflects overall outcome (see §6.1).

**Email count and folder distribution defaults**: light tier = 50 emails (60% inbox / 30% sent / 10% drafts = 30/15/5); medium = 100 (2×); heavy = 200 (4×). This is a distinct scale from the contact/event tier multipliers, stated explicitly rather than forced to match.

---

### FR-4: Mailbox Reset (`reset` command)

**Input**: either `--batch-id <id>` (selective) or `--wipe-all` (full wipe); IMAP connection details as in FR-3.

**Behavior — selective (default mode, `--batch-id`)**:
1. Opens one IMAP connection.
2. Per folder (INBOX, Sent, Drafts): `SEARCH HEADER X-WM8-Seed-Batch <batch-id>`.
3. Flags matched UIDs `\Deleted`, then `UID EXPUNGE` on that specific UID set (RFC 4315 — does not expunge other messages flagged deleted for unrelated reasons).
4. Applies the same throttling as seeding between per-folder operations.
5. Reports counts removed per folder.

**Behavior — full wipe (`--wipe-all`)**:
1. Requires explicit interactive confirmation (typed confirmation, not just a flag) before proceeding — this is destructive and unscoped.
2. Per folder: `SEARCH ALL`, flag `\Deleted`, `EXPUNGE` (unscoped).
3. Reports counts removed per folder.

**Both modes**: does not touch contacts or calendar data (manual UI operation, out of scope). Records the run via History Logger (FR-5), including which mode was used.

**Trash-folder note**: if the mail backend moves expunged messages to a server-side Trash rather than hard-deleting, this is an accepted outcome, not a defect — no additional Trash-clearing step is required (see §10 item 1).

---

### FR-5: Run History (`history` command)

**Input**: optional `--mailbox <address>` filter; optional `--limit <n>`.

**Behavior**:
- Reads `history.jsonl` (append-only, written by every `seed` and `reset` run — see §5 for entry schema).
- Displays runs in reverse-chronological order by default: timestamp, mailbox, server host, action, batch-id, item counts, status.
- Filters to a single mailbox if `--mailbox` is supplied.

**Output**: terminal display only, no mutation. This command never touches the network or credentials.

---

### FR-6: Credential Handling (cross-cutting, applies to `seed` and `reset`)

- Password is never accepted as a CLI argument.
- Accepted via either: (a) interactive prompt (hidden input, not echoed to terminal), or (b) a credentials file at an operator-specified path (passed via `--creds-file`), enforced mode `600`, read once per invocation. Format: flat `key=value` (`server=...`, `username=...`, `password=...`). Recommended placement is a `*.creds` file in the project directory, which is covered by the repo's `.gitignore`.
- Server host and username may be passed as CLI arguments (not secret) or included in the credentials file.
- Full detail and rationale in §4.

---

## 4. Non-Functional Requirements

### NFR-1: Rate Limiting / Abuse-Avoidance (Shared Infrastructure)

This is a correctness requirement, not a performance optimization — target mail clusters are commonly shared infrastructure, and behavior that reads as automated abuse risks account restriction or connection blocking, defeating the tool's purpose entirely.

- **Single connection, sequential execution**: one IMAP session per invocation. No concurrent connections to the same mailbox, no parallelizing across mailboxes for speed.
- **Minimum inter-request delay**: a floor delay between every `APPEND` call and every per-folder `SEARCH`/`EXPUNGE` operation during reset. Default 1.5 seconds, configurable via `--delay-min`/`--delay-max`.
- **Jitter, not fixed cadence**: delay is randomized within a configurable range (default 1–3 seconds), not a constant interval — uniform request timing is itself a detectable automation signature.
- **Batch ceiling with cooldown**: after every N consecutive operations (default N=10, configurable via `--cooldown-every`), pause for an extended interval (default 10 seconds) before continuing.
- **Backoff on server pushback**: if the server returns an error indicative of throttling (rate-limit-style response, unexpected connection drop mid-batch), apply exponential backoff (e.g., 2s → 4s → 8s, capped, max 3 retries for that specific operation) before either succeeding or marking that item permanently failed. This does not retry the whole batch — only the specific failed operation.
- **Tuning caveat**: these defaults are starting points, not validated against any specific server's real monitoring thresholds (untestable in advance — see §8.3). Expect adjustment based on real-world observation.

### NFR-2: Credential Security

- IMAP password is never accepted as a CLI argument (visible in shell history and process listings via `ps`).
- Accepted via interactive hidden-input prompt, or a credentials file (flat `key=value` format) at an operator-specified path (via `--creds-file`) with enforced `600` permissions — the tool checks the file's permission bits at read time and refuses to proceed (with a clear error) if the file is more permissive than `600`.
- Password is held in memory only for the duration of the IMAP session and is never written to disk, logged, or included in error messages/stack traces.
- **Platform caveat**: the `600`-permissions check assumes POSIX file permissions. Windows support requires separate design (see §9).

### NFR-3: History Log Integrity and Exclusions

- `history.jsonl` is append-only; no entry is ever mutated or deleted by the tool itself.
- The password is never written to the log, in any form — not redacted, not hashed, not present. Username and server host are logged (identifying but not secret).
- Log file permissions match the credentials file requirement (`600`).

### NFR-4: Idempotency and Safe Repetition

- `generate` (FR-2) is idempotent: re-running with the same `dataset.json` and output directory overwrites the same two files, no accumulation of stale output.
- `seed` (FR-3) is explicitly **not** idempotent by design — each run creates a new batch tagged with a new UUID, additive to whatever is already in the mailbox. This is intentional (supports iterative demo building) but must be documented clearly so it isn't mistaken for a bug when re-running `seed` doubles the mailbox contents.
- `reset --wipe-all` is the one genuinely destructive, non-recoverable operation in the tool and is gated behind explicit interactive confirmation (FR-4) for that reason.

### NFR-5: Scale and Complexity Boundaries

- This is a single-operator, single-mailbox-at-a-time, local CLI tool. It is explicitly not designed for concurrent multi-operator use, a shared database, or a service deployment.
- Volume tiers (light/medium/heavy) are the only scale dimension this tool needs to handle. No requirement exists for datasets beyond "heavy," and none should be speculatively built.

### NFR-6: Data Privacy

- All generated contact, email, and calendar content is synthetic. The tool must not be pointed at real client data as a content source — `dataset.json` is AI-generated fictional content, not derived from any real person or business. This is a usage constraint on the operator, not a technical control the tool enforces.

### NFR-7: Failure Reporting Clarity

- Every command that can partially fail (`seed`, `reset`) must produce a summary distinguishing succeeded/failed counts and reasons — silent partial success is treated as a defect, not an acceptable simplification.

---

## 5. Data Models

### 5.1 `dataset.json` — Generation Hand-off Schema

The contract between Stage 0 (manual AI generation) and the deterministic CLI.

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "SynthDataMailDataset",
  "type": "object",
  "required": ["persona", "contacts", "emails", "events"],
  "properties": {
    "persona": {
      "type": "object",
      "required": ["business_name", "business_type"],
      "properties": {
        "business_name": { "type": "string" },
        "business_type": { "type": "string" }
      }
    },
    "contacts": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["contact_id", "full_name", "email", "role"],
        "properties": {
          "contact_id": { "type": "string", "description": "Stable unique ID, referenced by emails[] and events[]" },
          "full_name": { "type": "string" },
          "email": { "type": "string", "format": "email" },
          "company": { "type": "string" },
          "role": { "type": "string", "description": "e.g. client, vendor, internal, partner" },
          "phone": { "type": "string" }
        }
      }
    },
    "emails": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["email_id", "folder", "contact_id", "direction", "subject", "body", "timestamp", "read"],
        "properties": {
          "email_id": { "type": "string" },
          "folder": { "type": "string", "enum": ["inbox", "sent", "drafts"] },
          "contact_id": { "type": "string", "description": "The contact this message is to/from, depending on direction" },
          "direction": { "type": "string", "enum": ["incoming", "outgoing"], "description": "incoming = contact is sender (inbox); outgoing = contact is recipient (sent/drafts)" },
          "subject": { "type": "string" },
          "body": { "type": "string" },
          "timestamp": { "type": "string", "format": "date-time", "description": "Must be past-only relative to generation time; see FR-2a" },
          "read": { "type": "boolean" },
          "thread_id": { "type": "string", "description": "Optional. Groups related messages; used to set In-Reply-To/References headers." },
          "in_reply_to_email_id": { "type": "string", "description": "Optional. References another email_id in this same array." }
        }
      }
    },
    "events": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["event_id", "title", "start", "end", "attendee_contact_ids"],
        "properties": {
          "event_id": { "type": "string" },
          "title": { "type": "string" },
          "description": { "type": "string" },
          "start": { "type": "string", "format": "date-time", "description": "Past-and-future distribution; see FR-2a" },
          "end": { "type": "string", "format": "date-time" },
          "attendee_contact_ids": {
            "type": "array",
            "items": { "type": "string" },
            "description": "Each must resolve to a contact_id in contacts[]"
          },
          "related_email_thread_id": { "type": "string", "description": "Optional. Ties event to an email thread_id for narrative coherence." }
        }
      }
    }
  }
}
```

**Referential integrity rules enforced by the Validator (beyond what JSON Schema alone expresses):**
- Every `emails[].contact_id` must exist in `contacts[].contact_id`.
- Every `events[].attendee_contact_ids[]` entry must exist in `contacts[].contact_id`.
- Every `emails[].in_reply_to_email_id`, if present, must exist in `emails[].email_id`.
- Every `events[].related_email_thread_id`, if present, must match at least one `emails[].thread_id`.

---

### 5.2 Custom Email Descriptor Schema

Input to `--custom-email`, per FR-3 step 4.

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "CustomEmailDescriptor",
  "type": "object",
  "required": ["subject", "from_name", "from_email", "html_file"],
  "properties": {
    "subject": { "type": "string" },
    "from_name": { "type": "string" },
    "from_email": { "type": "string", "format": "email" },
    "html_file": { "type": "string", "description": "Path relative to the descriptor file, pointing to the HTML body content." }
  }
}
```

This object is intentionally excluded from the `contacts`/foreign-key system in §5.1 — it is operator-authored, not AI-generated, and does not need a `contact_id`. The tool constructs it as `multipart/alternative` with an auto-derived plain-text fallback (tag-stripped from the HTML).

---

### 5.3 History Log Entry Schema (`history.jsonl`)

One JSON object per line, append-only.

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "HistoryLogEntry",
  "type": "object",
  "required": ["timestamp", "mailbox", "server_host", "action", "status"],
  "properties": {
    "timestamp": { "type": "string", "format": "date-time" },
    "mailbox": { "type": "string", "format": "email" },
    "server_host": { "type": "string" },
    "action": { "type": "string", "enum": ["seed", "reset"] },
    "batch_id": { "type": "string", "description": "Present for both seed and reset (selective)" },
    "reset_mode": { "type": "string", "enum": ["selective", "wipe_all"], "description": "Present only when action=reset" },
    "volume_tier": { "type": "string", "enum": ["light", "medium", "heavy"], "description": "Present only when action=seed" },
    "counts": {
      "type": "object",
      "properties": {
        "attempted": { "type": "integer" },
        "succeeded": { "type": "integer" },
        "failed": { "type": "integer" }
      }
    },
    "status": { "type": "string", "enum": ["success", "partial", "failed"] }
  }
}
```

**Explicit exclusion**: no property in this schema may ever hold a password, in any form. The logger's function signature should not have access to the password value at all, not merely "know not to log it."

---

### 5.4 Entity Relationship Summary

```
contacts[contact_id] ◄──────────┬── emails[contact_id]
                                 └── events[attendee_contact_ids[]]

emails[thread_id] ◄────── events[related_email_thread_id]   (optional link)

emails[in_reply_to_email_id] ──► emails[email_id]            (optional, within array)

history.jsonl[batch_id] ──► (mailbox state tagged with X-WM8-Seed-Batch header, not a JSON reference — cross-system link via IMAP header)
```

The custom email (§5.2) is deliberately outside this graph — no incoming or outgoing references.

---

## 6. API Contracts

This tool has no external service API — no REST endpoints, no web server. "API Contracts" here means the two interfaces that actually govern correctness: the CLI argument/exit-code contract, and the IMAP command contract.

### 6.1 CLI Contract

**`synthdata-mail validate --dataset <path>`**
- Exit 0: valid, prints counts.
- Exit 1: invalid, prints every schema violation and dangling reference found.

**`synthdata-mail generate --dataset <path> [--output-dir <path>]`**
- Default `--output-dir`: `./output/`
- Exit 0: `contacts.vcf` and `events.ics` written.
- Exit 1: validation failed; no files written.

**`synthdata-mail seed --dataset <path> --server <host> --username <email> [--custom-email <path-to-json>] [--batch-id <uuid>] [--delay-min <seconds>] [--delay-max <seconds>] [--cooldown-every <n>]`**
- Password: never a flag. Prompted interactively (hidden input) unless `--creds-file <path>` is supplied, in which case the file is read (must be mode `600`, or the command exits 1 with an explicit permissions error before attempting any connection).
- Defaults: `--delay-min 1.5`, `--delay-max 3`, `--cooldown-every 10`.
- `--batch-id`: auto-generated UUID v4 if omitted; printed to stdout regardless, since it's needed for later reset.
- Exit 0: all messages appended successfully.
- Exit 1: validation failed, connection failed, or credentials file permissions rejected — no messages appended.
- Exit 2: partial success — some messages appended, some failed. Summary printed to stdout; per-message failures printed to stderr.

**`synthdata-mail reset --server <host> --username <email> (--batch-id <uuid> | --wipe-all)`**
- Password: same rules as `seed`.
- `--wipe-all`: requires interactive typed confirmation (`type "WIPE" to confirm`); non-interactive/scripted invocation without a way to supply this confirmation is expected to fail closed, not proceed.
- Exit 0: full success.
- Exit 1: connection/auth failure — no messages removed.
- Exit 2: partial success.

**`synthdata-mail history [--mailbox <email>] [--limit <n>]`**
- No network activity, no credentials required.
- Exit 0 always (empty history is not an error).
- Output: terminal table, reverse-chronological.

**Global**: no flag on any command ever accepts a password value directly. Any implementation that adds a `--password` flag is non-conformant with this spec regardless of convenience.

### 6.2 IMAP Command Contract

**Connection**: SSL/TLS only (no plaintext IMAP). Single connection per invocation, held open for the duration of the command, closed cleanly on completion or fatal error.

**Folder targeting** (server-agnostic by default, since this tool is not tied to one webmail product):
- Primary mechanism: resolve `sent`/`drafts` via IMAP special-use attributes (`\Sent`, `\Drafts`) queried from the server's folder list.
- Fallback: if special-use attributes are unavailable, attempt literal folder names in this order: `Sent`, `Sent Items`, `Sent Messages` (for sent); `Drafts` (for drafts).
- **Confirmed case**: for WM8 specifically, the operator has verified the account's actual folder list is literal — `Inbox`, `Spam`, `Drafts`, `Sent`, `Trash` (no special-use attribute dependency needed for this target). Implementations targeting WM8 can rely on these literal names directly; this is a confirmed default, not a guess, but should still be spot-checked against the specific target mailbox before first production use, since naming may vary by account or cluster (see §10 item 2).
- If neither special-use attributes nor any fallback literal name resolves a folder, the command must fail with an explicit error naming the folder it could not find — not silently default to INBOX or skip the message.

**APPEND** (via `imap_tools` `MailBox.append()` or equivalent):
- Internal date: set explicitly per the dataset's `timestamp` field — must not default to "now" for any synthetic message.
- Flags: `\Seen` set if `read: true`, unset otherwise. No other flags set unless explicitly extended later.
- Custom header: `X-WM8-Seed-Batch: <batch-id>` added to every message's header block before APPEND, synthetic and custom alike. (Header name retained for stability across the tool's development history; not indicative of a WM8-only scope.)

**SEARCH** (reset):
- `SEARCH HEADER X-WM8-Seed-Batch <batch-id>`, issued per-folder (INBOX, Sent, Drafts), not globally — IMAP SEARCH operates on the currently selected folder only, so this is three sequential SELECT+SEARCH operations, not one.

**STORE + EXPUNGE** (reset):
- `UID STORE <uids> +FLAGS.SILENT (\Deleted)` followed by `UID EXPUNGE <uids>` (RFC 4315 targeted expunge) for selective reset.
- Plain `STORE ALL ... EXPUNGE` (untargeted) for `--wipe-all`.
- If the server does not support `UID EXPUNGE` (no `UIDPLUS` capability), implementation must detect this via capability check before relying on it, and document the limitation rather than silently performing an untargeted expunge under a selective-reset command name.

**Error classification** (for retry/backoff logic in NFR-1): connection-level errors (timeout, reset) and authentication errors are treated as fatal for the current operation and subject to backoff/retry per NFR-1; malformed-message errors (e.g., APPEND rejected for a specific message) are treated as a per-item failure, logged, and skipped — not retried.

---

## 7. Tech Stack

| Layer | Choice | Rationale |
|---|---|---|
| Language | Python 3.11+ | Standalone local CLI/automation script — the case the default TypeScript/Next.js stack explicitly carves out for Python. |
| IMAP client | `imap_tools` | Maintained, provides `APPEND` with explicit internal-date and flag control in one call; avoids hand-rolling `imaplib` protocol details. |
| vCard generation | `vobject` | Mature RFC 6350-compliant vCard construction. |
| iCalendar generation | `icalendar` | Mature RFC 5545-compliant `VEVENT`/attendee construction. |
| Schema validation | `jsonschema` | Standard JSON Schema validator; used for `dataset.json` and the custom-email descriptor. |
| CLI framework | `click` | Decorator-based subcommand ergonomics across five subcommands (validate/generate/seed/reset/history); cleaner generated code than `argparse` for this shape, and the extra dependency is a non-issue for a local single-operator script. |
| Logging/history | Stdlib `json` + append-only file I/O | No database — single-user local tool, a DB would be over-engineering per NFR-5. |
| Content generation (Stage 0) | Claude Code / Claude Cowork, manual, no API key | No Anthropic API key available to the operator; decoupled manual step rather than runtime API integration. |

**Explicit deviations from default stack:**
- No TypeScript/Next.js — this is not a web app, has no UI beyond a terminal.
- No Supabase — no persistent multi-user data store needed; local JSONL file suffices at this scale.
- No Vercel — nothing to deploy; this runs on the operator's machine against a remote mailbox.
- Version control: GitHub remains appropriate for source control, without a deployment pipeline attached.

---

## 8. Testing Requirements

Integration and end-to-end only. No unit tests unless separately requested.

### 8.1 Integration Tests

**IMAP APPEND correctness**
- Setup: a disposable/test mailbox (not a real client account — see 8.4).
- Test: append a message with a specific past `timestamp` and `read: false`; fetch it back; assert internal date matches (within server rounding tolerance) and `\Seen` is unset.
- Test: append to each of the three folders (inbox/sent/drafts); assert each lands in the correct folder via folder-specific fetch, using the folder-targeting contract in §6.2 (special-use attribute resolution, or confirmed literal names for WM8).
- Test: append with `X-WM8-Seed-Batch` header; assert `SEARCH HEADER X-WM8-Seed-Batch <id>` returns exactly that message.

**Selective reset correctness**
- Setup: seed two batches with different `batch-id` values into the same test mailbox.
- Test: reset batch A by ID; assert batch A's messages are gone (via SEARCH) and batch B's messages remain untouched.

**Custom email ordering**
- Setup: seed a full synthetic batch plus a `--custom-email`.
- Test: assert the custom email's internal date is later than every synthetic message's internal date in the same batch, that it is unread, and that its MIME structure is `multipart/alternative` with both HTML and derived plain-text parts present.

**Throttling behavior (measurable, not just present in code)**
- Test: seed a batch of N messages with a known `--delay-min`/`--delay-max`; measure wall-clock time of the seed operation; assert elapsed time is consistent with N-1 delays having been applied.

**Partial failure handling**
- Test: simulate a mid-batch connection drop; assert the command exits 2, reports correct succeeded/failed counts, and that the already-succeeded messages are present in the mailbox.

**Date distribution (FR-2a)**
- Test: validate a fixture `dataset.json` against the date-distribution constraints — all email timestamps in the past relative to a fixed reference "now," all event timestamps within the -30/+60 day window — flagging this as a fixture/data-quality check rather than something the CLI enforces at runtime (the CLI validates schema and referential integrity, not date-range compliance; see §8.3).

### 8.2 End-to-End Tests

**Full lifecycle**
- `generate` from a fixed fixture `dataset.json` → assert `contacts.vcf` and `events.ics` are well-formed (parseable by `vobject`/`icalendar` on read-back) and match the fixture's contact/event counts.
- `seed` the same fixture against a disposable test mailbox → assert mailbox message count matches dataset email count (+1 if a custom email was included).
- `history` → assert the run appears with correct mailbox, counts, and status.
- `reset --batch-id` using the ID from the seed step → assert mailbox returns to pre-seed message count.
- `history` again → assert the reset run also appears, with correct counts removed.

### 8.3 Explicitly Untestable As Specced (flagged, not silently skipped)

- **Content coherence/quality of AI-generated `dataset.json`** cannot be asserted by automated test — referential integrity is testable and covered under `validate`, but whether generated email subject lines and bodies read as plausible business correspondence is a human judgment call, made once per generation by reviewing output before running `seed`.
- **Actual abuse-detection avoidance on a live shared mail cluster** — NFR-1's throttling parameters are testable for "does the delay code run as configured," but whether those specific values are sufficient to avoid triggering any given mail cluster's real monitoring is not verifiable in a test environment. This is a tuning parameter to adjust based on real-world observation, not a testable guarantee.
- **Server-side Trash accumulation** — accepted as a known outcome (§10 item 1), not something a test needs to assert against.

### 8.4 Environment/Data Setup Required

- A disposable or dedicated test mailbox is a hard prerequisite for §8.1 and §8.2 — these tests must never run against a live client demo account.
- Fixture `dataset.json` files (valid and intentionally-invalid variants, for testing the validator's failure path) should be checked into the repo under a `test/fixtures/` directory.

---

## 9. Out of Scope

- **CalDAV/CardDAV write transport**: contacts and calendar events are generated as files (`contacts.vcf`, `events.ics`) for manual bulk import through the target webmail's UI. This tool does not connect to any CalDAV/CardDAV service. Evaluated and explicitly descoped due to lack of assumed write access and to avoid building transport for a UI-supported manual path.
- **Contacts/calendar reset**: because there is no write transport for these, reset (FR-4) only ever touches mailbox (IMAP) content. Removing seeded contacts/calendar entries from a demo account is a manual operation in the webmail UI, symmetric with how they were added.
- **SMTP relay / actual mail delivery**: no email in this tool is ever sent externally. All mailbox population is via direct IMAP injection into the target account's own storage.
- **Multi-operator / concurrent use**: this is a single-operator local CLI. No user accounts, no shared server deployment, no concurrent-access handling for the history log or credentials file.
- **AI generation at runtime**: no Anthropic API integration in the CLI. Content generation is a manual, external step performed via Claude Code/Cowork (§2, Stage 0), decoupled from this codebase entirely.
- **Templating engine for the custom email**: `--custom-email` accepts a fixed JSON descriptor plus a static HTML file. No variable substitution, no merge-field system.
- **Trash-folder emptying**: reset operations expunge from INBOX/Sent/Drafts only. If the backend routes expunged messages to a server-side Trash, this is accepted (§10 item 1) and not handled.
- **Non-English content generation / localization**: the dataset schema and generation prompt assume English-language business correspondence.
- **Windows support for the credentials-file permission check**: the `600`-permissions enforcement (NFR-2) assumes POSIX file permissions.
- **Recurring calendar events**: the event schema (§5.1) supports single-instance events only. No RRULE-equivalent fields or recurrence handling.

---

## 10. Open Questions — Resolved

All items below were open during spec development and have since been resolved. Recorded here for traceability rather than removed.

1. **Trash-folder behavior on EXPUNGE** — Resolved: acceptable if expunged messages land in a server-side Trash. No Trash-clearing step required in `reset` (FR-4). Known, accepted side effect, not a defect.

2. **Sent/Drafts folder naming** — Resolved via operator-provided screenshot of an actual WM8 account: folder names are literal — `Inbox`, `Spam`, `Drafts`, `Sent`, `Trash`. §6.2 uses special-use-attribute resolution as the general-purpose default (since this tool is not WM8-only), with these confirmed literal names as a documented fallback/override for WM8 specifically. Flag: confirmed against one account's folder list; spot-check against the actual target mailbox before first production seed run, in case naming varies by account/cluster.

3. **Volume-tier email counts** — Resolved: light tier = 50 emails, medium = 100 (2×), heavy = 200 (4×). Split across folders: 60% inbox / 30% sent / 10% drafts by default.

4. **Plain-text fallback for custom HTML email** — Resolved: yes. Custom email is constructed as `multipart/alternative`, with the plain-text part auto-derived from the HTML body (tag-stripped).

5. **Throttling parameter tuning** — Resolved: keep stated defaults (1.5–3s jitter, cooldown every 10 operations, 10s extended pause). Explicitly not validated against any real cluster's monitoring thresholds; expect post-launch tuning.

6. **`click` vs `argparse`** — Resolved: `click`, for cleaner decorator-based subcommand ergonomics.

7. **Recurring calendar events** — Resolved: out of scope (moved to §9).

8. **Credentials file format** — Resolved: flat `key=value` file (`server=...`, `username=...`, `password=...`).

### Additional requirement surfaced during resolution

**Date distribution for generated content** (see FR-2a): emails must be past-only (90-day lookback for light/medium, 180-day for heavy, skewed recent); events span -30/+60 days from generation time. Applies to the Stage 0 generation prompt template; the deterministic CLI validates schema/referential integrity but does not enforce or resample date ranges.

### Naming note

This tool was originally scoped and named around the WM8 rollout specifically (`wm8seed`) before being generalized to any IMAP-accessible mailbox and renamed **synthdata-mail**. The `X-WM8-Seed-Batch` header name was retained as-is through this rename for stability rather than renamed to something generic — this is a cosmetic inconsistency worth knowing about, not a functional issue, since the header's content (a UUID) and behavior are unaffected by its name.
