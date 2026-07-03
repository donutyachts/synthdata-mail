import json
from pathlib import Path

import pytest
import vobject
from icalendar import Calendar

from synthdata_mail.generator import write_contacts_vcf, write_events_ics

FIXTURES = Path(__file__).parent / "fixtures"


def load_valid() -> dict:
    return json.loads((FIXTURES / "valid_dataset.json").read_text())


class TestContactsVcf:
    def test_writes_all_contacts(self, tmp_path):
        data = load_valid()
        n = write_contacts_vcf(data["contacts"], tmp_path / "contacts.vcf")
        assert n == len(data["contacts"])

    def test_vcf_is_parseable(self, tmp_path):
        data = load_valid()
        out = tmp_path / "contacts.vcf"
        write_contacts_vcf(data["contacts"], out)
        content = out.read_text()
        cards = list(vobject.readComponents(content))
        assert len(cards) == len(data["contacts"])

    def test_vcf_has_correct_emails(self, tmp_path):
        data = load_valid()
        out = tmp_path / "contacts.vcf"
        write_contacts_vcf(data["contacts"], out)
        content = out.read_text()
        cards = list(vobject.readComponents(content))
        emails_in_vcf = {c.email.value for c in cards}
        expected = {c["email"] for c in data["contacts"]}
        assert emails_in_vcf == expected

    def test_vcf_includes_company_and_phone(self, tmp_path):
        data = load_valid()
        out = tmp_path / "contacts.vcf"
        write_contacts_vcf(data["contacts"], out)
        content = out.read_text()
        # Alice has company and phone
        assert "Acme Corp" in content
        assert "+1-555-0101" in content

    def test_idempotent_overwrite(self, tmp_path):
        data = load_valid()
        out = tmp_path / "contacts.vcf"
        write_contacts_vcf(data["contacts"], out)
        size1 = out.stat().st_size
        write_contacts_vcf(data["contacts"], out)
        size2 = out.stat().st_size
        assert size1 == size2

    def test_creates_output_dir(self, tmp_path):
        data = load_valid()
        out = tmp_path / "nested" / "dir" / "contacts.vcf"
        write_contacts_vcf(data["contacts"], out)
        assert out.exists()


class TestEventsIcs:
    def test_writes_all_events(self, tmp_path):
        data = load_valid()
        n = write_events_ics(data["events"], data["contacts"], tmp_path / "events.ics")
        assert n == len(data["events"])

    def test_ics_is_parseable(self, tmp_path):
        data = load_valid()
        out = tmp_path / "events.ics"
        write_events_ics(data["events"], data["contacts"], out)
        cal = Calendar.from_ical(out.read_bytes())
        vevents = [c for c in cal.walk() if c.name == "VEVENT"]
        assert len(vevents) == len(data["events"])

    def test_ics_event_titles(self, tmp_path):
        data = load_valid()
        out = tmp_path / "events.ics"
        write_events_ics(data["events"], data["contacts"], out)
        cal = Calendar.from_ical(out.read_bytes())
        summaries = {c["SUMMARY"] for c in cal.walk() if c.name == "VEVENT"}
        expected = {e["title"] for e in data["events"]}
        assert summaries == expected

    def test_ics_has_attendees(self, tmp_path):
        data = load_valid()
        out = tmp_path / "events.ics"
        write_events_ics(data["events"], data["contacts"], out)
        content = out.read_bytes().decode("utf-8", errors="replace")
        # ev1 has c1 (alice) and c2 (bob) as attendees
        assert "alice@example.com" in content
        assert "bob@vendor.com" in content

    def test_idempotent_overwrite(self, tmp_path):
        data = load_valid()
        out = tmp_path / "events.ics"
        write_events_ics(data["events"], data["contacts"], out)
        size1 = out.stat().st_size
        write_events_ics(data["events"], data["contacts"], out)
        size2 = out.stat().st_size
        assert size1 == size2
