import json
import os
from pathlib import Path

import pytest

import synthdata_mail.history as hist_module


@pytest.fixture(autouse=True)
def temp_history(tmp_path, monkeypatch):
    """Redirect history file to a temp path for each test."""
    history_path = tmp_path / "history.jsonl"
    monkeypatch.setattr(hist_module, "HISTORY_FILE", history_path)
    yield history_path


class TestHistoryLog:
    def test_log_seed_run(self, temp_history):
        hist_module.log_run(
            mailbox="test@example.com",
            server_host="mail.example.com",
            action="seed",
            batch_id="batch-001",
            volume_tier="light",
            counts={"attempted": 50, "succeeded": 50, "failed": 0},
            status="success",
        )
        lines = temp_history.read_text().splitlines()
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["action"] == "seed"
        assert entry["batch_id"] == "batch-001"
        assert entry["volume_tier"] == "light"
        assert entry["status"] == "success"

    def test_log_reset_run(self, temp_history):
        hist_module.log_run(
            mailbox="test@example.com",
            server_host="mail.example.com",
            action="reset",
            batch_id="batch-001",
            reset_mode="selective",
            counts={"attempted": 50, "succeeded": 50, "failed": 0},
            status="success",
        )
        entry = json.loads(temp_history.read_text().strip())
        assert entry["action"] == "reset"
        assert entry["reset_mode"] == "selective"

    def test_no_password_in_log(self, temp_history):
        hist_module.log_run(
            mailbox="test@example.com",
            server_host="mail.example.com",
            action="seed",
            batch_id="batch-001",
            status="success",
        )
        content = temp_history.read_text()
        assert "password" not in content.lower()
        assert "secret" not in content.lower()

    def test_append_only(self, temp_history):
        for i in range(3):
            hist_module.log_run(
                mailbox="test@example.com",
                server_host="mail.example.com",
                action="seed",
                batch_id=f"batch-{i:03d}",
                status="success",
            )
        lines = temp_history.read_text().splitlines()
        assert len(lines) == 3

    def test_read_history_reverse_chronological(self, temp_history):
        for i in range(3):
            hist_module.log_run(
                mailbox="test@example.com",
                server_host="mail.example.com",
                action="seed",
                batch_id=f"batch-{i:03d}",
                status="success",
            )
        entries = hist_module.read_history()
        # Most recent first
        assert entries[0]["batch_id"] == "batch-002"
        assert entries[-1]["batch_id"] == "batch-000"

    def test_read_history_filter_by_mailbox(self, temp_history):
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
        entries = hist_module.read_history(mailbox="alice@example.com")
        assert len(entries) == 1
        assert entries[0]["batch_id"] == "batch-a"

    def test_read_history_limit(self, temp_history):
        for i in range(5):
            hist_module.log_run(
                mailbox="test@example.com",
                server_host="mail.example.com",
                action="seed",
                batch_id=f"batch-{i:03d}",
                status="success",
            )
        entries = hist_module.read_history(limit=2)
        assert len(entries) == 2

    def test_read_empty_history(self, temp_history):
        entries = hist_module.read_history()
        assert entries == []

    def test_file_permissions(self, temp_history):
        hist_module.log_run(
            mailbox="test@example.com",
            server_host="mail.example.com",
            action="seed",
            batch_id="batch-001",
            status="success",
        )
        mode = oct(os.stat(temp_history).st_mode)
        assert mode.endswith("600")
