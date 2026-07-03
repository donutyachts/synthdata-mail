"""CLI integration tests (no network, no IMAP)."""
import json
import os
from pathlib import Path

import pytest
from click.testing import CliRunner

from synthdata_mail.cli import cli

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def runner():
    return CliRunner()


class TestValidateCommand:
    def test_valid_dataset_exits_0(self, runner):
        result = runner.invoke(cli, ["validate", "--dataset", str(FIXTURES / "valid_dataset.json")])
        assert result.exit_code == 0
        assert "3 contacts" in result.output
        assert "4 emails" in result.output
        assert "2 events" in result.output

    def test_invalid_schema_exits_1(self, runner):
        result = runner.invoke(cli, ["validate", "--dataset", str(FIXTURES / "invalid_dataset_schema.json")])
        assert result.exit_code == 1

    def test_dangling_refs_exits_1(self, runner):
        result = runner.invoke(cli, ["validate", "--dataset", str(FIXTURES / "invalid_dataset_dangling_refs.json")])
        assert result.exit_code == 1
        assert "c-does-not-exist" in result.output or "c-does-not-exist" in (result.output + str(result.exception))

    def test_missing_file_exits_1(self, runner):
        result = runner.invoke(cli, ["validate", "--dataset", "/nonexistent/path.json"])
        assert result.exit_code == 1


class TestGenerateCommand:
    def test_generates_output_files(self, runner, tmp_path):
        result = runner.invoke(
            cli,
            ["generate", "--dataset", str(FIXTURES / "valid_dataset.json"), "--output-dir", str(tmp_path)],
        )
        assert result.exit_code == 0
        assert (tmp_path / "contacts.vcf").exists()
        assert (tmp_path / "events.ics").exists()

    def test_contacts_vcf_parseable(self, runner, tmp_path):
        runner.invoke(
            cli,
            ["generate", "--dataset", str(FIXTURES / "valid_dataset.json"), "--output-dir", str(tmp_path)],
        )
        import vobject
        content = (tmp_path / "contacts.vcf").read_text()
        cards = list(vobject.readComponents(content))
        assert len(cards) == 3  # valid_dataset has 3 contacts

    def test_events_ics_parseable(self, runner, tmp_path):
        runner.invoke(
            cli,
            ["generate", "--dataset", str(FIXTURES / "valid_dataset.json"), "--output-dir", str(tmp_path)],
        )
        from icalendar import Calendar
        content = (tmp_path / "events.ics").read_bytes()
        cal = Calendar.from_ical(content)
        vevents = [c for c in cal.walk() if c.name == "VEVENT"]
        assert len(vevents) == 2  # valid_dataset has 2 events

    def test_invalid_dataset_exits_1(self, runner, tmp_path):
        result = runner.invoke(
            cli,
            ["generate", "--dataset", str(FIXTURES / "invalid_dataset_schema.json"), "--output-dir", str(tmp_path)],
        )
        assert result.exit_code == 1
        assert not (tmp_path / "contacts.vcf").exists()

    def test_default_output_dir(self, runner, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(
            cli,
            ["generate", "--dataset", str(FIXTURES / "valid_dataset.json")],
        )
        assert result.exit_code == 0
        assert (tmp_path / "output" / "contacts.vcf").exists()

    def test_idempotent(self, runner, tmp_path):
        args = ["generate", "--dataset", str(FIXTURES / "valid_dataset.json"), "--output-dir", str(tmp_path)]
        runner.invoke(cli, args)
        size1 = (tmp_path / "contacts.vcf").stat().st_size
        runner.invoke(cli, args)
        size2 = (tmp_path / "contacts.vcf").stat().st_size
        assert size1 == size2


class TestHistoryCommand:
    def test_empty_history(self, runner, tmp_path, monkeypatch):
        import synthdata_mail.history as hist_module
        monkeypatch.setattr(hist_module, "HISTORY_FILE", tmp_path / "history.jsonl")
        result = runner.invoke(cli, ["history"])
        assert result.exit_code == 0
        assert "No history" in result.output

    def test_shows_logged_run(self, runner, tmp_path, monkeypatch):
        import synthdata_mail.history as hist_module
        history_path = tmp_path / "history.jsonl"
        monkeypatch.setattr(hist_module, "HISTORY_FILE", history_path)
        hist_module.log_run(
            mailbox="demo@example.com",
            server_host="mail.example.com",
            action="seed",
            batch_id="batch-abc",
            counts={"attempted": 50, "succeeded": 50, "failed": 0},
            status="success",
        )
        result = runner.invoke(cli, ["history"])
        assert result.exit_code == 0
        assert "batch-abc" in result.output
        assert "seed" in result.output

    def test_filter_by_mailbox(self, runner, tmp_path, monkeypatch):
        import synthdata_mail.history as hist_module
        history_path = tmp_path / "history.jsonl"
        monkeypatch.setattr(hist_module, "HISTORY_FILE", history_path)
        hist_module.log_run(
            mailbox="alice@example.com",
            server_host="mail.example.com",
            action="seed",
            batch_id="batch-a",
            status="success",
        )
        hist_module.log_run(
            mailbox="bob@example.com",
            server_host="mail.example.com",
            action="seed",
            batch_id="batch-b",
            status="success",
        )
        result = runner.invoke(cli, ["history", "--mailbox", "alice@example.com"])
        assert "batch-a" in result.output
        assert "batch-b" not in result.output


class TestResetCommandValidation:
    def test_requires_batch_id_or_wipe_all(self, runner):
        result = runner.invoke(cli, ["reset", "--server", "mail.example.com", "--username", "test@example.com"])
        assert result.exit_code == 1

    def test_batch_id_and_wipe_all_mutually_exclusive(self, runner):
        result = runner.invoke(
            cli,
            ["reset", "--server", "mail.example.com", "--username", "test@example.com",
             "--batch-id", "some-id", "--wipe-all"]
        )
        assert result.exit_code == 1


class TestDateDistributionFixture:
    """Validates the fixture against FR-2a date distribution rules."""

    def test_email_timestamps_are_past(self):
        from datetime import datetime, timezone
        data = json.loads((FIXTURES / "valid_dataset.json").read_text())
        now = datetime(2026, 7, 3, 0, 0, 0, tzinfo=timezone.utc)
        for email in data["emails"]:
            dt = datetime.fromisoformat(email["timestamp"].replace("Z", "+00:00"))
            assert dt < now, f"Email {email['email_id']} has future timestamp: {dt}"
