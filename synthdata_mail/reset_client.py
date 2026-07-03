import time
import random

import imap_tools

from .imap_client import _resolve_folder


_TARGET_FOLDERS = ["inbox", "sent", "drafts"]


def _has_uidplus(mb: imap_tools.MailBox) -> bool:
    """Check if server supports UIDPLUS (targeted UID EXPUNGE)."""
    typ, caps = mb.client.capability()
    if typ != "OK":
        return False
    caps_str = b" ".join(caps).decode(errors="replace").upper()
    return "UIDPLUS" in caps_str


def _throttle(delay_min: float, delay_max: float) -> None:
    time.sleep(random.uniform(delay_min, delay_max))


def reset_by_batch_id(
    *,
    server: str,
    username: str,
    password: str,
    batch_id: str,
    delay_min: float,
    delay_max: float,
) -> dict[str, int]:
    """Remove messages tagged with batch_id. Returns {folder: count_removed}."""
    counts: dict[str, int] = {}

    with imap_tools.MailBox(server).login(username, password) as mb:
        has_uidplus = _has_uidplus(mb)

        for logical_folder in _TARGET_FOLDERS:
            try:
                folder_name = _resolve_folder(mb, logical_folder)
            except ValueError:
                counts[logical_folder] = 0
                continue

            mb.folder.set(folder_name)
            # Search for messages with batch header
            try:
                messages = list(mb.fetch(
                    imap_tools.AND(header=[f"X-WM8-Seed-Batch {batch_id}"]),
                    mark_seen=False,
                    bulk=True,
                ))
            except Exception:
                counts[logical_folder] = 0
                _throttle(delay_min, delay_max)
                continue

            if not messages:
                counts[logical_folder] = 0
                _throttle(delay_min, delay_max)
                continue

            uids = [str(m.uid) for m in messages]
            uid_str = ",".join(uids)

            # Flag as deleted
            mb.client.uid("STORE", uid_str, "+FLAGS.SILENT", "(\\Deleted)")

            if has_uidplus:
                mb.client.uid("EXPUNGE", uid_str)
            else:
                # Fallback: untargeted expunge — log the limitation
                import sys
                print(
                    f"Warning: server does not support UIDPLUS; using untargeted EXPUNGE "
                    f"for folder '{folder_name}'. Other \\Deleted messages may also be expunged.",
                    file=sys.stderr,
                )
                mb.client.expunge()

            counts[logical_folder] = len(uids)
            _throttle(delay_min, delay_max)

    return counts


def wipe_all(
    *,
    server: str,
    username: str,
    password: str,
    delay_min: float,
    delay_max: float,
) -> dict[str, int]:
    """Wipe all messages from INBOX/Sent/Drafts. Returns {folder: count_removed}."""
    counts: dict[str, int] = {}

    with imap_tools.MailBox(server).login(username, password) as mb:
        for logical_folder in _TARGET_FOLDERS:
            try:
                folder_name = _resolve_folder(mb, logical_folder)
            except ValueError:
                counts[logical_folder] = 0
                continue

            mb.folder.set(folder_name)
            try:
                messages = list(mb.fetch(imap_tools.AND(), mark_seen=False, bulk=True))
            except Exception:
                counts[logical_folder] = 0
                _throttle(delay_min, delay_max)
                continue

            if not messages:
                counts[logical_folder] = 0
                _throttle(delay_min, delay_max)
                continue

            uids = ",".join(str(m.uid) for m in messages)
            mb.client.uid("STORE", uids, "+FLAGS.SILENT", "(\\Deleted)")
            mb.client.expunge()
            counts[logical_folder] = len(messages)
            _throttle(delay_min, delay_max)

    return counts
