import sys
import uuid
from pathlib import Path

import click

from .credentials import CredentialError, load_credentials
from .generator import write_contacts_vcf, write_events_ics
from .history import log_run, read_history
from .imap_client import seed_mailbox
from .reset_client import reset_by_batch_id, wipe_all
from .validator import validate_and_report


@click.group()
def cli():
    """synthdata-mail — populate IMAP mailboxes with synthetic demo data."""


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--dataset", required=True, help="Path to dataset.json")
def validate(dataset: str):
    """Validate dataset.json structure and referential integrity."""
    data, errors = validate_and_report(dataset)
    if errors:
        for err in errors:
            click.echo(f"ERROR: {err}", err=True)
        sys.exit(1)

    contacts = len(data["contacts"])
    emails = len(data["emails"])
    events = len(data["events"])
    click.echo(f"Valid. {contacts} contacts, {emails} emails, {events} events.")


# ---------------------------------------------------------------------------
# generate
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--dataset", required=True, help="Path to dataset.json")
@click.option("--output-dir", default="./output", show_default=True, help="Output directory")
def generate(dataset: str, output_dir: str):
    """Generate contacts.vcf and events.ics from a validated dataset."""
    data, errors = validate_and_report(dataset)
    if errors:
        for err in errors:
            click.echo(f"ERROR: {err}", err=True)
        sys.exit(1)

    out = Path(output_dir)
    n_contacts = write_contacts_vcf(data["contacts"], out / "contacts.vcf")
    n_events = write_events_ics(data["events"], data["contacts"], out / "events.ics")

    click.echo(f"Written: {out / 'contacts.vcf'} ({n_contacts} contacts)")
    click.echo(f"Written: {out / 'events.ics'} ({n_events} events)")


# ---------------------------------------------------------------------------
# seed
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--dataset", required=True, help="Path to dataset.json")
@click.option("--server", default=None, help="IMAP server hostname")
@click.option("--username", default=None, help="IMAP username / mailbox address")
@click.option("--creds-file", default=None, help="Path to credentials file (mode 600)")
@click.option("--custom-email", default=None, help="Path to custom email descriptor JSON")
@click.option("--batch-id", default=None, help="Batch UUID (auto-generated if omitted)")
@click.option("--delay-min", default=1.5, show_default=True, type=float, help="Min inter-request delay (seconds)")
@click.option("--delay-max", default=3.0, show_default=True, type=float, help="Max inter-request delay (seconds)")
@click.option("--cooldown-every", default=10, show_default=True, type=int, help="Cooldown after N operations")
def seed(
    dataset: str,
    server: str | None,
    username: str | None,
    creds_file: str | None,
    custom_email: str | None,
    batch_id: str | None,
    delay_min: float,
    delay_max: float,
    cooldown_every: int,
):
    """Seed an IMAP mailbox with synthetic emails from a dataset."""
    data, errors = validate_and_report(dataset)
    if errors:
        for err in errors:
            click.echo(f"ERROR: {err}", err=True)
        sys.exit(1)

    try:
        resolved_server, resolved_username, password = load_credentials(
            server, username, creds_file
        )
    except CredentialError as e:
        click.echo(f"ERROR: {e}", err=True)
        sys.exit(1)

    effective_batch_id = batch_id or str(uuid.uuid4())
    click.echo(f"Batch ID: {effective_batch_id}")
    click.echo(f"Seeding {len(data['emails'])} emails to {resolved_username}@{resolved_server} ...")

    try:
        succeeded, failed, failures = seed_mailbox(
            dataset=data,
            server=resolved_server,
            username=resolved_username,
            password=password,
            batch_id=effective_batch_id,
            custom_email_path=custom_email,
            delay_min=delay_min,
            delay_max=delay_max,
            cooldown_every=cooldown_every,
        )
    except Exception as e:
        click.echo(f"ERROR: Connection/auth failure: {e}", err=True)
        log_run(
            mailbox=resolved_username,
            server_host=resolved_server,
            action="seed",
            batch_id=effective_batch_id,
            counts={"attempted": 0, "succeeded": 0, "failed": 0},
            status="failed",
        )
        sys.exit(1)

    total = succeeded + failed
    click.echo(f"\nResult: {succeeded}/{total} messages appended successfully.")
    if failures:
        click.echo("Failures:", err=True)
        for f in failures:
            click.echo(f"  {f}", err=True)

    status = "success" if failed == 0 else ("partial" if succeeded > 0 else "failed")
    log_run(
        mailbox=resolved_username,
        server_host=resolved_server,
        action="seed",
        batch_id=effective_batch_id,
        counts={"attempted": total, "succeeded": succeeded, "failed": failed},
        status=status,
    )

    if failed > 0 and succeeded == 0:
        sys.exit(1)
    elif failed > 0:
        sys.exit(2)


# ---------------------------------------------------------------------------
# reset
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--server", default=None, help="IMAP server hostname")
@click.option("--username", default=None, help="IMAP username / mailbox address")
@click.option("--creds-file", default=None, help="Path to credentials file (mode 600)")
@click.option("--batch-id", default=None, help="Batch ID to remove (selective reset)")
@click.option("--wipe-all", "do_wipe_all", is_flag=True, default=False, help="Wipe all messages from INBOX/Sent/Drafts")
@click.option("--delay-min", default=1.5, show_default=True, type=float)
@click.option("--delay-max", default=3.0, show_default=True, type=float)
def reset(
    server: str | None,
    username: str | None,
    creds_file: str | None,
    batch_id: str | None,
    do_wipe_all: bool,
    delay_min: float,
    delay_max: float,
):
    """Remove seeded messages from an IMAP mailbox."""
    if not batch_id and not do_wipe_all:
        click.echo("ERROR: Supply --batch-id <id> or --wipe-all.", err=True)
        sys.exit(1)
    if batch_id and do_wipe_all:
        click.echo("ERROR: --batch-id and --wipe-all are mutually exclusive.", err=True)
        sys.exit(1)

    try:
        resolved_server, resolved_username, password = load_credentials(
            server, username, creds_file
        )
    except CredentialError as e:
        click.echo(f"ERROR: {e}", err=True)
        sys.exit(1)

    if do_wipe_all:
        click.echo(
            "WARNING: This will delete ALL messages from INBOX, Sent, and Drafts.",
            err=True,
        )
        confirm = click.prompt('Type "WIPE" to confirm')
        if confirm != "WIPE":
            click.echo("Aborted — confirmation did not match.", err=True)
            sys.exit(1)

        try:
            counts = wipe_all(
                server=resolved_server,
                username=resolved_username,
                password=password,
                delay_min=delay_min,
                delay_max=delay_max,
            )
        except Exception as e:
            click.echo(f"ERROR: {e}", err=True)
            log_run(
                mailbox=resolved_username,
                server_host=resolved_server,
                action="reset",
                reset_mode="wipe_all",
                counts={"attempted": 0, "succeeded": 0, "failed": 0},
                status="failed",
            )
            sys.exit(1)

        total = sum(counts.values())
        for folder, n in counts.items():
            click.echo(f"  {folder}: {n} removed")
        click.echo(f"Wipe complete. {total} messages removed.")
        log_run(
            mailbox=resolved_username,
            server_host=resolved_server,
            action="reset",
            reset_mode="wipe_all",
            counts={"attempted": total, "succeeded": total, "failed": 0},
            status="success",
        )
    else:
        click.echo(f"Resetting batch {batch_id} from {resolved_username}@{resolved_server} ...")
        try:
            counts = reset_by_batch_id(
                server=resolved_server,
                username=resolved_username,
                password=password,
                batch_id=batch_id,
                delay_min=delay_min,
                delay_max=delay_max,
            )
        except Exception as e:
            click.echo(f"ERROR: {e}", err=True)
            log_run(
                mailbox=resolved_username,
                server_host=resolved_server,
                action="reset",
                batch_id=batch_id,
                reset_mode="selective",
                counts={"attempted": 0, "succeeded": 0, "failed": 0},
                status="failed",
            )
            sys.exit(1)

        total = sum(counts.values())
        for folder, n in counts.items():
            click.echo(f"  {folder}: {n} removed")
        click.echo(f"Reset complete. {total} messages removed.")
        log_run(
            mailbox=resolved_username,
            server_host=resolved_server,
            action="reset",
            batch_id=batch_id,
            reset_mode="selective",
            counts={"attempted": total, "succeeded": total, "failed": 0},
            status="success",
        )


# ---------------------------------------------------------------------------
# history
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--mailbox", default=None, help="Filter by mailbox address")
@click.option("--limit", default=None, type=int, help="Maximum number of entries to show")
def history(mailbox: str | None, limit: int | None):
    """Show run history."""
    entries = read_history(mailbox=mailbox, limit=limit)
    if not entries:
        click.echo("No history found.")
        return

    for entry in entries:
        ts = entry.get("timestamp", "?")
        action = entry.get("action", "?")
        mb = entry.get("mailbox", "?")
        host = entry.get("server_host", "?")
        bid = entry.get("batch_id", "-")
        status = entry.get("status", "?")
        counts = entry.get("counts", {})
        tier = entry.get("volume_tier", "")
        mode = entry.get("reset_mode", "")

        detail_parts = []
        if tier:
            detail_parts.append(f"tier={tier}")
        if mode:
            detail_parts.append(f"mode={mode}")
        if counts:
            detail_parts.append(
                f"ok={counts.get('succeeded', 0)} fail={counts.get('failed', 0)}"
            )
        detail = " ".join(detail_parts)

        click.echo(
            f"{ts}  {action:6s}  {status:8s}  {mb}@{host}  batch={bid}  {detail}"
        )
