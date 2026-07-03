import os
import stat
from pathlib import Path

import pytest

from synthdata_mail.credentials import CredentialError, load_credentials


class TestCredentialFile:
    def test_rejects_world_readable_file(self, tmp_path):
        creds = tmp_path / "creds"
        creds.write_text("server=mail.example.com\nusername=test\npassword=secret\n")
        os.chmod(creds, 0o644)
        with pytest.raises(CredentialError, match="unsafe permissions"):
            load_credentials(None, None, str(creds))

    def test_rejects_group_readable_file(self, tmp_path):
        creds = tmp_path / "creds"
        creds.write_text("server=mail.example.com\nusername=test\npassword=secret\n")
        os.chmod(creds, 0o640)
        with pytest.raises(CredentialError, match="unsafe permissions"):
            load_credentials(None, None, str(creds))

    def test_accepts_mode_600(self, tmp_path, monkeypatch):
        creds = tmp_path / "creds"
        creds.write_text("server=mail.example.com\nusername=test@example.com\npassword=secret\n")
        os.chmod(creds, 0o600)
        server, username, password = load_credentials(None, None, str(creds))
        assert server == "mail.example.com"
        assert username == "test@example.com"
        assert password == "secret"

    def test_cli_args_override_file(self, tmp_path):
        creds = tmp_path / "creds"
        creds.write_text("server=old.example.com\nusername=old@example.com\npassword=secret\n")
        os.chmod(creds, 0o600)
        server, username, password = load_credentials(
            "new.example.com", "new@example.com", str(creds)
        )
        assert server == "new.example.com"
        assert username == "new@example.com"

    def test_missing_file_raises(self):
        with pytest.raises(CredentialError, match="not found"):
            load_credentials(None, None, "/nonexistent/creds")

    def test_missing_server_raises(self, tmp_path, monkeypatch):
        creds = tmp_path / "creds"
        creds.write_text("username=test\npassword=secret\n")
        os.chmod(creds, 0o600)
        with pytest.raises(CredentialError, match="server"):
            load_credentials(None, None, str(creds))

    def test_missing_username_raises(self, tmp_path, monkeypatch):
        creds = tmp_path / "creds"
        creds.write_text("server=mail.example.com\npassword=secret\n")
        os.chmod(creds, 0o600)
        with pytest.raises(CredentialError, match="[Uu]sername"):
            load_credentials(None, None, str(creds))
