import html
import imaplib
import json
import random
import re
import time
import uuid
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, formatdate
from pathlib import Path

import imap_tools


def _parse_dt(dt_str: str) -> datetime:
    dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _strip_html(html_content: str) -> str:
    """Derive plain text from HTML via tag stripping."""
    text = re.sub(r"<br\s*/?>", "\n", html_content, flags=re.IGNORECASE)
    text = re.sub(r"<p[^>]*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</p>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _text_to_html(text: str) -> str:
    """Convert plain text body to HTML paragraphs."""
    escaped = html.escape(text)
    paragraphs = re.split(r"\n{2,}", escaped.strip())
    parts = []
    for para in paragraphs:
        lines = para.replace("\n", "<br>\n")
        parts.append(f"<p>{lines}</p>")
    return "\n".join(parts)


def _contact_signature_html(contact: dict) -> str:
    lines = [f"<strong>{html.escape(contact['full_name'])}</strong>"]
    if contact.get("role"):
        lines.append(html.escape(contact["role"]))
    if contact.get("company"):
        lines.append(html.escape(contact["company"]))
    if contact.get("email"):
        e = html.escape(contact["email"])
        lines.append(f'<a href="mailto:{e}">{e}</a>')
    if contact.get("phone"):
        lines.append(html.escape(contact["phone"]))
    return "<br>\n".join(lines)


def _contact_signature_text(contact: dict) -> str:
    parts = [contact["full_name"]]
    if contact.get("role"):
        parts.append(contact["role"])
    if contact.get("company"):
        parts.append(contact["company"])
    if contact.get("email"):
        parts.append(contact["email"])
    if contact.get("phone"):
        parts.append(contact["phone"])
    return "\n".join(parts)


def _persona_signature_html(persona: dict) -> str:
    name = html.escape(persona.get("business_name", ""))
    btype = html.escape(persona.get("business_type", ""))
    if btype:
        return f"<strong>{name}</strong><br>\n{btype}"
    return f"<strong>{name}</strong>"


def _persona_signature_text(persona: dict) -> str:
    parts = [persona.get("business_name", "")]
    if persona.get("business_type"):
        parts.append(persona["business_type"])
    return "\n".join(parts)


_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  body {{ font-family: Georgia, serif; font-size: 15px; line-height: 1.6;
         color: #222; margin: 0; padding: 0; background: #f5f5f5; }}
  .wrapper {{ max-width: 640px; margin: 0 auto; background: #fff;
              padding: 32px 36px; }}
  p {{ margin: 0 0 1em 0; }}
  .sig {{ margin-top: 2em; padding-top: 1em; border-top: 1px solid #ddd;
          font-size: 13px; color: #555; line-height: 1.5; }}
  .sig a {{ color: #555; text-decoration: none; }}
</style>
</head>
<body>
<div class="wrapper">
{body}
<div class="sig">
{sig}
</div>
</div>
</body>
</html>
"""


def _resolve_folder(mailbox: imap_tools.MailBox, target: str) -> str:
    """Resolve logical folder name to server folder name."""
    if target == "inbox":
        return "INBOX"

    special_use = {
        "sent": r"\Sent",
        "drafts": r"\Drafts",
    }
    fallbacks = {
        "sent": ["Sent", "Sent Items", "Sent Messages"],
        "drafts": ["Drafts"],
    }

    # Try special-use attributes
    attr_flag = special_use.get(target, "")
    folders = mailbox.folder.list()
    for folder in folders:
        if attr_flag and attr_flag in (folder.flags or []):
            return folder.name

    # Fallback to literal names
    existing_names = {f.name for f in folders}
    for name in fallbacks.get(target, []):
        if name in existing_names:
            return name

    raise ValueError(
        f"Could not resolve folder '{target}'. "
        f"Tried special-use {attr_flag!r} and literal names {fallbacks.get(target, [])}. "
        f"Available folders: {sorted(existing_names)}"
    )


def _build_message(
    email_data: dict,
    contact_map: dict,
    batch_id: str,
    message_id_map: dict,
    persona: dict,
) -> bytes:
    contact = contact_map[email_data["contact_id"]]
    direction = email_data["direction"]

    if direction == "incoming":
        from_addr = formataddr((contact["full_name"], contact["email"]))
        to_addr = ""
        sig_html = _contact_signature_html(contact)
        sig_text = _contact_signature_text(contact)
    else:
        from_addr = ""
        to_addr = formataddr((contact["full_name"], contact["email"]))
        sig_html = _persona_signature_html(persona)
        sig_text = _persona_signature_text(persona)

    body_html = _text_to_html(email_data["body"])
    html_content = _HTML_TEMPLATE.format(body=body_html, sig=sig_html)
    plain_content = email_data["body"] + "\n\n--\n" + sig_text

    msg = MIMEMultipart("alternative")
    msg["Subject"] = email_data["subject"]
    msg["From"] = from_addr or "Demo User <demo@example.com>"
    msg["To"] = to_addr or "Demo User <demo@example.com>"
    msg["Date"] = formatdate(
        _parse_dt(email_data["timestamp"]).timestamp(), localtime=False
    )

    msg_id = f"<{email_data['email_id']}@synthdata-mail>"
    msg["Message-ID"] = msg_id
    message_id_map[email_data["email_id"]] = msg_id

    if email_data.get("thread_id"):
        msg["X-Thread-ID"] = email_data["thread_id"]

    if email_data.get("in_reply_to_email_id"):
        parent_msg_id = message_id_map.get(
            email_data["in_reply_to_email_id"],
            f"<{email_data['in_reply_to_email_id']}@synthdata-mail>",
        )
        msg["In-Reply-To"] = parent_msg_id
        msg["References"] = parent_msg_id

    msg["X-WM8-Seed-Batch"] = batch_id

    msg.attach(MIMEText(plain_content, "plain", "utf-8"))
    msg.attach(MIMEText(html_content, "html", "utf-8"))

    return msg.as_bytes()


def _build_custom_message(descriptor: dict, html_content: str, batch_id: str, internal_dt: datetime) -> bytes:
    plain_text = _strip_html(html_content)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = descriptor["subject"]
    msg["From"] = formataddr((descriptor["from_name"], descriptor["from_email"]))
    msg["To"] = "Demo User <demo@example.com>"
    msg["Date"] = formatdate(internal_dt.timestamp(), localtime=False)
    msg["Message-ID"] = f"<custom-{uuid.uuid4()}@synthdata-mail>"
    msg["X-WM8-Seed-Batch"] = batch_id

    msg.attach(MIMEText(plain_text, "plain", "utf-8"))
    msg.attach(MIMEText(html_content, "html", "utf-8"))

    return msg.as_bytes()


class ThrottledMailbox:
    def __init__(
        self,
        mailbox: imap_tools.MailBox,
        delay_min: float,
        delay_max: float,
        cooldown_every: int,
        cooldown_duration: float = 10.0,
    ):
        self._mb = mailbox
        self._delay_min = delay_min
        self._delay_max = delay_max
        self._cooldown_every = cooldown_every
        self._cooldown_duration = cooldown_duration
        self._op_count = 0

    def _throttle(self) -> None:
        self._op_count += 1
        if self._op_count > 1 and (self._op_count - 1) % self._cooldown_every == 0:
            time.sleep(self._cooldown_duration)
        else:
            time.sleep(random.uniform(self._delay_min, self._delay_max))

    def append(
        self,
        folder: str,
        message_bytes: bytes,
        dt: datetime,
        flags: tuple[str, ...],
        max_retries: int = 3,
    ) -> bool:
        """Append with backoff retry. Returns True on success."""
        backoff = 2.0
        for attempt in range(max_retries + 1):
            try:
                self._throttle()
                self._mb.append(message_bytes, folder, dt=dt, flag_set=list(flags))
                return True
            except (imap_tools.errors.ImapToolsError, OSError) as e:
                err_str = str(e)
                # Per-message malformed rejection — don't retry
                if "BAD" in err_str.upper():
                    raise
                if attempt < max_retries:
                    time.sleep(backoff)
                    backoff = min(backoff * 2, 30)
                else:
                    raise
        return False


def seed_mailbox(
    *,
    dataset: dict,
    server: str,
    username: str,
    password: str,
    batch_id: str,
    custom_email_path: str | None,
    delay_min: float,
    delay_max: float,
    cooldown_every: int,
) -> tuple[int, int, list[str]]:
    """Seed the mailbox. Returns (succeeded, failed, failure_reasons)."""
    contact_map = {c["contact_id"]: c for c in dataset["contacts"]}
    emails = dataset["emails"]
    persona = dataset.get("persona", {})

    succeeded = 0
    failed = 0
    failures = []
    message_id_map: dict[str, str] = {}

    with imap_tools.MailBox(server).login(username, password) as mb:
        throttled = ThrottledMailbox(mb, delay_min, delay_max, cooldown_every)

        folder_cache: dict[str, str] = {}

        def resolve(target: str) -> str:
            if target not in folder_cache:
                folder_cache[target] = _resolve_folder(mb, target)
            return folder_cache[target]

        max_dt = None

        for idx, email_data in enumerate(emails):
            try:
                folder_name = resolve(email_data["folder"])
                msg_bytes = _build_message(email_data, contact_map, batch_id, message_id_map, persona)
                dt = _parse_dt(email_data["timestamp"])
                flags = ("\\Seen",) if email_data.get("read") else ()
                throttled.append(folder_name, msg_bytes, dt, flags)
                succeeded += 1
                if max_dt is None or dt > max_dt:
                    max_dt = dt
            except Exception as e:
                failed += 1
                reason = f"[{idx}] email_id={email_data.get('email_id', '?')}: {e}"
                failures.append(reason)

        # Custom email — must be newest
        if custom_email_path:
            try:
                desc_path = Path(custom_email_path)
                descriptor = json.loads(desc_path.read_text())
                html_path = desc_path.parent / descriptor["html_file"]
                html_content = html_path.read_text(encoding="utf-8")

                if max_dt is None:
                    from datetime import timedelta
                    custom_dt = datetime.now(timezone.utc)
                else:
                    from datetime import timedelta
                    custom_dt = max_dt.replace(tzinfo=timezone.utc if max_dt.tzinfo is None else max_dt.tzinfo) + timedelta(seconds=1)

                msg_bytes = _build_custom_message(descriptor, html_content, batch_id, custom_dt)
                inbox_name = resolve("inbox")
                throttled.append(inbox_name, msg_bytes, custom_dt, ())
                succeeded += 1
            except Exception as e:
                failed += 1
                failures.append(f"[custom-email]: {e}")

    return succeeded, failed, failures
