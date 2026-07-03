import json
import os
import stat
from datetime import datetime, timezone
from pathlib import Path

HISTORY_FILE = Path("history.jsonl")


def _ensure_restricted(path: Path) -> None:
    if path.exists():
        mode = path.stat().st_mode
        if mode & (stat.S_IRWXG | stat.S_IRWXO):
            os.chmod(path, 0o600)
    else:
        path.touch(mode=0o600)


def log_run(
    *,
    mailbox: str,
    server_host: str,
    action: str,
    batch_id: str | None = None,
    reset_mode: str | None = None,
    volume_tier: str | None = None,
    counts: dict | None = None,
    status: str,
) -> None:
    entry: dict = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "mailbox": mailbox,
        "server_host": server_host,
        "action": action,
        "status": status,
    }
    if batch_id is not None:
        entry["batch_id"] = batch_id
    if reset_mode is not None:
        entry["reset_mode"] = reset_mode
    if volume_tier is not None:
        entry["volume_tier"] = volume_tier
    if counts is not None:
        entry["counts"] = counts

    _ensure_restricted(HISTORY_FILE)
    with open(HISTORY_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")


def read_history(mailbox: str | None = None, limit: int | None = None) -> list[dict]:
    if not HISTORY_FILE.exists():
        return []
    entries = []
    with open(HISTORY_FILE) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if mailbox and entry.get("mailbox") != mailbox:
                continue
            entries.append(entry)
    entries.reverse()
    if limit:
        entries = entries[:limit]
    return entries
