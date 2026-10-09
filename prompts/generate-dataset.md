# Generate Dataset — synthdata-mail Stage 0 Prompt Template

This is not code — it's a prompt you run manually in Claude Code or Claude Cowork to produce `dataset.json`. Copy the prompt below, fill in the three bracketed parameters, and run it. Save the output as `dataset.json` and validate it with `synthdata-mail validate --dataset dataset.json` before using it.

---

## Parameters to fill in before running

- **VOLUME_TIER**: `light`, `medium`, or `heavy`
- **BUSINESS_PERSONA**: a short description, e.g. "generic small business, mixed clients and vendors" or "professional services firm (law/consulting/accounting)"
- **LANGUAGE**: `EN` (English), `ES` (Spanish), or `FR` (French) — the language all generated content is written in

---

## The prompt

```
Generate a synthetic dataset for populating a demo email account. Output ONLY a single valid JSON object matching the schema below — no preamble, no markdown code fences, no explanation before or after.

PARAMETERS:
- Volume tier: {VOLUME_TIER}
- Business persona: {BUSINESS_PERSONA}
- Language: {LANGUAGE}
- Generation reference time: use the current date/time as "now" for all relative date calculations below.

VOLUME TARGETS BY TIER (follow exactly):
- light:  15 contacts, 20 events, 50 emails
- medium: 30 contacts, 50 events, 100 emails
- heavy:  50 contacts, 100 events, 200 emails

Use the row matching the specified Volume tier.

EMAIL FOLDER SPLIT (applies within the total email count above):
- 60% inbox, 30% sent, 10% drafts (round sensibly, e.g. light tier = 30 inbox / 15 sent / 5 drafts)

SCHEMA — the output must be a single JSON object with this exact shape:

{
  "persona": {
    "business_name": string,
    "business_type": string
  },
  "contacts": [
    {
      "contact_id": string (unique, e.g. "c001"),
      "full_name": string,
      "email": string (valid email format, domain should look plausible for the contact's company),
      "company": string,
      "role": string (the contact's job title, written in the dataset language, e.g. "Purchasing Manager", "Jefe de Compras", "Directrice commerciale" — shown in their email signature and as the address-book title, so never a relationship label like "client" or "vendor"),
      "phone": string
    }
  ],
  "emails": [
    {
      "email_id": string (unique, e.g. "e001"),
      "folder": "inbox" | "sent" | "drafts",
      "contact_id": string (must match a contact_id from contacts[] above — no exceptions),
      "direction": "incoming" | "outgoing",
      "subject": string,
      "body": string (a few sentences to a short paragraph, realistic business tone matching the persona and the contact's relationship to the business),
      "timestamp": string (ISO 8601 date-time — see DATE RULES below),
      "read": boolean,
      "thread_id": string (optional — use to group 2-4 related emails into a back-and-forth conversation),
      "in_reply_to_email_id": string (optional — if this email is a reply, reference the email_id it replies to; that email must appear earlier in the array)
    }
  ],
  "events": [
    {
      "event_id": string (unique, e.g. "v001"),
      "title": string,
      "description": string,
      "start": string (ISO 8601 date-time — see DATE RULES below),
      "end": string (ISO 8601 date-time, after start, typically 30-90 minutes later),
      "attendee_contact_ids": [string, ...] (each must match a contact_id from contacts[] above — no exceptions),
      "related_email_thread_id": string (optional — if this event relates to an email conversation, reference that thread_id)
    }
  ]
}

LANGUAGE RULES (applies to the Language parameter above):
- EN = English, ES = Spanish, FR = French.
- Write ALL human-readable content in the specified language: business_name, business_type, company names, email subjects and bodies, event titles and descriptions.
- Make the persona and contacts culturally plausible for that language: names, company names, phone number formats, and email domains should fit a business operating in a region where that language is spoken (e.g. ES → Spain or Latin America, FR → France, Belgium, Switzerland, or Quebec). Pick one region and stay consistent across the dataset.
- Use natural, native-sounding business correspondence conventions for the language (greetings, sign-offs, formality level such as tú/usted or tu/vous appropriate to the relationship) — not literal translations of English phrasing.
- Reply subjects should use the conventional prefix for the language ("Re:" is acceptable in all three; "RE:" is also common in ES/FR).
- JSON keys and enumerated values stay in English exactly as shown in the schema ("inbox", "sent", "drafts", "incoming", "outgoing"). Only free-text values are localized, including each contact's role (job title).

DATE RULES (do not skip these — they are load-bearing, not decorative):
- Emails: every timestamp must be BEFORE the generation reference time (past-only, no future-dated emails, ever — a received or sent message cannot be dated in the future). Lookback window: 90 days back from now for light/medium tiers, 180 days back for heavy tier. Distribution should skew recent — put noticeably more emails in the last 2-3 weeks than in the earlier part of the window, tapering off further back. Do not spread emails evenly/uniformly across the window; a real inbox is denser near "now."
- Events: timestamps span BOTH past and future relative to the generation reference time. Window: 30 days before now to 60 days after now. Slightly favor upcoming (future) events over past ones, since a demo benefits more from showing what's coming up.
- Do not cluster multiple emails or events on the exact same date unless it's clearly intentional (e.g., two related meeting-prep emails the same day as the meeting itself).

COHERENCE REQUIREMENTS (this is the most important part — do not generate contacts, emails, and events independently):
1. Generate the persona and full contact list FIRST. Decide each contact's relationship to the business — a mix of clients, vendors, internal colleagues, and partners appropriate to the business type — and give them a job title (role) that fits it. The relationship itself is not stored; let it come through in their company, job title, and emails.
2. Every email's contact_id and every event's attendee_contact_ids must reference contacts you already created — never invent a new name inline in an email body or event title that isn't in contacts[].
3. Build a handful of genuine email THREADS (2-4 messages each, using thread_id and in_reply_to_email_id) rather than 100% standalone one-off messages — this is what makes an inbox look real.
4. Connect at least several events to email threads via related_email_thread_id where it makes narrative sense (e.g., an email thread negotiating a meeting time, followed by the actual calendar event for that meeting).
5. Vary tone and content by the contact's relationship to the business: a vendor's emails should read differently from a client's, which should read differently from an internal colleague's.
6. Do not use placeholder or obviously fake content (no "Lorem ipsum," no "Test Email 1," no sequentially numbered generic subjects). Every subject and body should read like something a real small business would actually send or receive.

OUTPUT FORMAT:
Return ONLY the JSON object. No markdown code fences (no ```json), no explanatory text before or after. The response must be directly parseable as JSON with no modification.
```

---

## After running the prompt

1. Save the raw output as `dataset.json`.
2. If the model wrapped the output in a markdown code fence despite the instruction not to, strip the fence before saving — the file must be valid JSON on its own, nothing else.
3. Run:
   ```bash
   synthdata-mail validate --dataset dataset.json
   ```
4. If validation fails on referential integrity (a `contact_id` that doesn't exist), the model likely invented a name inline instead of reusing the contact list. Re-run the prompt, or manually patch the dataset — for a small number of dangling references, it's often faster to fix the JSON by hand than regenerate the whole thing.
5. Skim the emails and events for tone/plausibility before seeding — per the spec (§8.3), content coherence and quality is a human judgment call, not something the validator checks. The validator confirms structure and references are internally consistent; it says nothing about whether the writing is any good.
6. Once you're satisfied, proceed to `generate` (files) and `seed` (mailbox) as described in the README.

## Notes on re-running for different demos

Each run of this prompt produces a different persona, contact list, and content — that's the point. There's no need to reuse a dataset across different client demos unless you specifically want to; regenerating fresh for each one is expected and cheap (a few minutes in Claude Code, no API cost since this runs through your existing Claude Code/Cowork access rather than a metered API).
