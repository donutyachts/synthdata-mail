import json
from pathlib import Path

import jsonschema

from .schema import DATASET_SCHEMA


def load_dataset(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Dataset file not found: {path}")
    with open(p) as f:
        return json.load(f)


def validate_dataset(dataset: dict) -> list[str]:
    """Return a list of error strings; empty list means valid."""
    errors = []

    # JSON Schema validation
    validator = jsonschema.Draft7Validator(
        DATASET_SCHEMA,
        format_checker=jsonschema.FormatChecker(),
    )
    for err in sorted(validator.iter_errors(dataset), key=lambda e: e.path):
        path = ".".join(str(p) for p in err.absolute_path) or "(root)"
        errors.append(f"Schema error at {path}: {err.message}")

    if errors:
        # Don't attempt referential integrity on structurally invalid data
        return errors

    contact_ids = {c["contact_id"] for c in dataset["contacts"]}
    email_ids = {e["email_id"] for e in dataset["emails"]}
    thread_ids = {e["thread_id"] for e in dataset["emails"] if e.get("thread_id")}

    for email in dataset["emails"]:
        cid = email["contact_id"]
        if cid not in contact_ids:
            errors.append(
                f"Dangling contact_id '{cid}' in email '{email['email_id']}'"
            )
        reply_to = email.get("in_reply_to_email_id")
        if reply_to and reply_to not in email_ids:
            errors.append(
                f"Dangling in_reply_to_email_id '{reply_to}' in email '{email['email_id']}'"
            )

    for event in dataset["events"]:
        for cid in event.get("attendee_contact_ids", []):
            if cid not in contact_ids:
                errors.append(
                    f"Dangling attendee contact_id '{cid}' in event '{event['event_id']}'"
                )
        rel_thread = event.get("related_email_thread_id")
        if rel_thread and rel_thread not in thread_ids:
            errors.append(
                f"Dangling related_email_thread_id '{rel_thread}' in event '{event['event_id']}'"
            )

    return errors


def validate_and_report(dataset_path: str) -> tuple[dict | None, list[str]]:
    """Load and validate a dataset. Returns (dataset, errors)."""
    try:
        dataset = load_dataset(dataset_path)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        return None, [str(e)]

    errors = validate_dataset(dataset)
    return dataset, errors
