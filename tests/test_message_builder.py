"""Tests for the RFC 822 message builder logic in imap_client."""
import email
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from synthdata_mail.imap_client import (
    _build_message,
    _build_custom_message,
    _strip_html,
)

FIXTURES = Path(__file__).parent / "fixtures"


def load_valid() -> dict:
    return json.loads((FIXTURES / "valid_dataset.json").read_text())


def make_contact_map(contacts: list) -> dict:
    return {c["contact_id"]: c for c in contacts}


class TestStripHtml:
    def test_removes_tags(self):
        result = _strip_html("<p>Hello <b>world</b></p>")
        assert "<" not in result
        assert "Hello" in result
        assert "world" in result

    def test_br_becomes_newline(self):
        result = _strip_html("Line 1<br>Line 2")
        assert "\n" in result

    def test_html_entities_decoded(self):
        # html.unescape decodes &amp; → &, &lt; → <, &gt; → >
        # This is correct behavior: plain text fallback should decode entities
        result = _strip_html("&amp; &lt; &gt;")
        assert "&" in result
        assert "<" in result  # &lt; decoded to <
        assert ">" in result  # &gt; decoded to >


class TestBuildMessage:
    def setup_method(self):
        self.data = load_valid()
        self.contact_map = make_contact_map(self.data["contacts"])
        self.batch_id = "test-batch-123"
        self.mid_map: dict = {}

    def _parse(self, email_data: dict) -> email.message.Message:
        raw = _build_message(email_data, self.contact_map, self.batch_id, self.mid_map)
        return email.message_from_bytes(raw)

    def test_batch_header_present(self):
        msg = self._parse(self.data["emails"][0])
        assert msg["X-WM8-Seed-Batch"] == self.batch_id

    def test_incoming_email_sets_from_contact(self):
        # e1 is incoming from c1 (Alice)
        email_data = next(e for e in self.data["emails"] if e["email_id"] == "e1")
        msg = self._parse(email_data)
        assert "alice@example.com" in msg["From"]

    def test_outgoing_email_sets_to_contact(self):
        # e2 is outgoing to c1 (Alice)
        email_data = next(e for e in self.data["emails"] if e["email_id"] == "e2")
        msg = self._parse(email_data)
        assert "alice@example.com" in msg["To"]

    def test_subject_is_set(self):
        email_data = self.data["emails"][0]
        msg = self._parse(email_data)
        assert msg["Subject"] == email_data["subject"]

    def test_message_id_stable(self):
        email_data = self.data["emails"][0]
        msg = self._parse(email_data)
        assert "e1@synthdata-mail" in msg["Message-ID"]

    def test_in_reply_to_set(self):
        # e2 replies to e1 — parse e1 first to populate mid_map
        e1 = next(e for e in self.data["emails"] if e["email_id"] == "e1")
        e2 = next(e for e in self.data["emails"] if e["email_id"] == "e2")
        _build_message(e1, self.contact_map, self.batch_id, self.mid_map)
        msg2 = email.message_from_bytes(
            _build_message(e2, self.contact_map, self.batch_id, self.mid_map)
        )
        assert "e1@synthdata-mail" in msg2.get("In-Reply-To", "")

    def test_thread_id_header(self):
        email_data = next(e for e in self.data["emails"] if e.get("thread_id"))
        msg = self._parse(email_data)
        assert msg["X-Thread-ID"] == email_data["thread_id"]


class TestBuildCustomMessage:
    def test_multipart_alternative(self):
        descriptor = {
            "subject": "Test Welcome",
            "from_name": "Demo Team",
            "from_email": "demo@acme.com",
            "html_file": "welcome.html",
        }
        html_content = "<h1>Hello</h1><p>Welcome!</p>"
        dt = datetime.now(timezone.utc)
        raw = _build_custom_message(descriptor, html_content, "batch-x", dt)
        msg = email.message_from_bytes(raw)
        assert msg.get_content_type() == "multipart/alternative"

    def test_has_html_and_plain_parts(self):
        descriptor = {
            "subject": "Test",
            "from_name": "Demo",
            "from_email": "demo@acme.com",
            "html_file": "welcome.html",
        }
        html_content = "<h1>Hello</h1><p>Welcome!</p>"
        dt = datetime.now(timezone.utc)
        raw = _build_custom_message(descriptor, html_content, "batch-x", dt)
        msg = email.message_from_bytes(raw)
        content_types = {part.get_content_type() for part in msg.get_payload()}
        assert "text/plain" in content_types
        assert "text/html" in content_types

    def test_batch_header_present(self):
        descriptor = {
            "subject": "Test",
            "from_name": "Demo",
            "from_email": "demo@acme.com",
            "html_file": "welcome.html",
        }
        raw = _build_custom_message(descriptor, "<p>hi</p>", "my-batch", datetime.now(timezone.utc))
        msg = email.message_from_bytes(raw)
        assert msg["X-WM8-Seed-Batch"] == "my-batch"

    def test_from_name_and_email(self):
        descriptor = {
            "subject": "Test",
            "from_name": "Acme Team",
            "from_email": "team@acme.com",
            "html_file": "welcome.html",
        }
        raw = _build_custom_message(descriptor, "<p>hi</p>", "b", datetime.now(timezone.utc))
        msg = email.message_from_bytes(raw)
        assert "team@acme.com" in msg["From"]
        assert "Acme Team" in msg["From"]
