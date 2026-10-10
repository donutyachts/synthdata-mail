import csv
import json
from pathlib import Path

import pytest
import vobject
from icalendar import Calendar

from synthdata_mail.generator import (
    CSV_COLUMNS,
    write_contacts_csv,
    write_contacts_vcf,
    write_events_ics,
)

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

    @pytest.mark.parametrize(
        "full_name, given, family",
        [
            ("Alice Smith", "Alice", "Smith"),
            ("Lucía Ferrer Navarro", "Lucía", "Ferrer Navarro"),
            ("Madonna", "", "Madonna"),
        ],
    )
    def test_vcf_name_split(self, tmp_path, full_name, given, family):
        out = tmp_path / "contacts.vcf"
        contact = {"contact_id": "c1", "full_name": full_name, "email": "x@example.com"}
        write_contacts_vcf([contact], out)
        card = next(vobject.readComponents(out.read_text()))
        assert card.n.value.given == given
        assert card.n.value.family == family

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


class TestContactsCsv:
    def test_writes_header_and_all_contacts(self, tmp_path):
        data = load_valid()
        out = tmp_path / "contacts.csv"
        n = write_contacts_csv(data["contacts"], out)
        with open(out, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        assert n == len(data["contacts"]) == len(rows)
        assert list(rows[0].keys()) == CSV_COLUMNS
        assert {r["E-mail Address"] for r in rows} == {c["email"] for c in data["contacts"]}

    def test_row_fields(self, tmp_path):
        out = tmp_path / "contacts.csv"
        contact = {
            "contact_id": "c1",
            "full_name": "Lucía Ferrer Navarro",
            "email": "lucia@example.es",
            "company": "Restaurante La Llotja, S.L.",
            "role": "Directora de sala",
            "phone": "+34 963 512 774",
        }
        write_contacts_csv([contact], out)
        with open(out, newline="", encoding="utf-8") as f:
            row = next(csv.DictReader(f))
        assert row == {
            "First Name": "Lucía",
            "Last Name": "Ferrer Navarro",
            "Display Name": "Lucía Ferrer Navarro",
            "E-mail Address": "lucia@example.es",
            "Company": "Restaurante La Llotja, S.L.",
            "Job Title": "Directora de sala",
            "Business Phone": "+34 963 512 774",
        }

    def test_optional_fields_blank(self, tmp_path):
        out = tmp_path / "contacts.csv"
        contact = {"contact_id": "c1", "full_name": "Madonna", "email": "m@example.com", "role": "Singer"}
        write_contacts_csv([contact], out)
        with open(out, newline="", encoding="utf-8") as f:
            row = next(csv.DictReader(f))
        assert row["First Name"] == ""
        assert row["Last Name"] == "Madonna"
        assert row["Company"] == ""
        assert row["Business Phone"] == ""


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

    def test_ics_offset_times_written_as_utc(self, tmp_path):
        out = tmp_path / "events.ics"
        event = {
            "event_id": "v1",
            "title": "Firma",
            "start": "2026-10-16T09:30:00+02:00",
            "end": "2026-10-16T10:30:00+02:00",
            "attendee_contact_ids": [],
        }
        write_events_ics([event], [], out)
        content = out.read_bytes().decode()
        assert "TZID" not in content
        assert "DTSTART:20261016T073000Z" in content
        assert "DTEND:20261016T083000Z" in content

    def test_idempotent_overwrite(self, tmp_path):
        data = load_valid()
        out = tmp_path / "events.ics"
        write_events_ics(data["events"], data["contacts"], out)
        size1 = out.stat().st_size
        write_events_ics(data["events"], data["contacts"], out)
        size2 = out.stat().st_size
        assert size1 == size2
