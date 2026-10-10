import csv
from datetime import datetime, timezone
from pathlib import Path

import vobject
from icalendar import Calendar, Event, vCalAddress, vText


def _split_name(full_name: str) -> tuple[str, str]:
    """Split full_name into (given, family) best-effort: first word is the
    given name, the rest the family name, so Spanish double surnames
    ("Lucía Ferrer Navarro") stay together."""
    parts = full_name.split(" ", 1)
    if len(parts) > 1:
        return parts[0], parts[1]
    return "", parts[0]


def write_contacts_vcf(contacts: list[dict], output_path: Path) -> int:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for contact in contacts:
        card = vobject.vCard()

        card.add("fn").value = contact["full_name"]

        given, family = _split_name(contact["full_name"])
        n = card.add("n")
        n.value = vobject.vcard.Name(family=family, given=given)

        email_prop = card.add("email")
        email_prop.value = contact["email"]
        email_prop.type_param = "INTERNET"

        if contact.get("company"):
            card.add("org").value = [contact["company"]]

        if contact.get("role"):
            card.add("title").value = contact["role"]

        if contact.get("phone"):
            phone_prop = card.add("tel")
            phone_prop.value = contact["phone"]
            phone_prop.type_param = "VOICE"

        lines.append(card.serialize())

    output_path.write_text("".join(lines), encoding="utf-8")
    return len(contacts)


# Outlook-style column names, which most webmail contact importers recognize.
CSV_COLUMNS = [
    "First Name",
    "Last Name",
    "Display Name",
    "E-mail Address",
    "Company",
    "Job Title",
    "Business Phone",
]


def write_contacts_csv(contacts: list[dict], output_path: Path) -> int:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(CSV_COLUMNS)
        for contact in contacts:
            given, family = _split_name(contact["full_name"])
            writer.writerow([
                given,
                family,
                contact["full_name"],
                contact["email"],
                contact.get("company", ""),
                contact.get("role", ""),
                contact.get("phone", ""),
            ])
    return len(contacts)


def _parse_dt(dt_str: str) -> datetime:
    """Parse ISO 8601 datetime, ensuring timezone-aware."""
    dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def write_events_ics(
    events: list[dict], contacts: list[dict], output_path: Path
) -> int:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    contact_map = {c["contact_id"]: c for c in contacts}

    cal = Calendar()
    cal.add("prodid", "-//synthdata-mail//EN")
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")

    for ev in events:
        vevent = Event()
        vevent.add("uid", ev["event_id"])
        vevent.add("summary", ev["title"])
        # Write UTC ("...Z"): fixed-offset datetimes otherwise serialize as
        # TZID="UTC+02:00" with no matching VTIMEZONE, which clients misread.
        vevent.add("dtstart", _parse_dt(ev["start"]).astimezone(timezone.utc))
        vevent.add("dtend", _parse_dt(ev["end"]).astimezone(timezone.utc))
        vevent.add("dtstamp", datetime.now(timezone.utc))

        if ev.get("description"):
            vevent.add("description", ev["description"])

        for cid in ev.get("attendee_contact_ids", []):
            contact = contact_map.get(cid)
            if contact:
                attendee = vCalAddress(f"mailto:{contact['email']}")
                attendee.params["CN"] = vText(contact["full_name"])
                attendee.params["ROLE"] = vText("REQ-PARTICIPANT")
                vevent.add("attendee", attendee, encode=0)

        cal.add_component(vevent)

    output_path.write_bytes(cal.to_ical())
    return len(events)
