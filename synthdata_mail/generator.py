from datetime import datetime, timezone
from pathlib import Path

import vobject
from icalendar import Calendar, Event, vCalAddress, vText


def write_contacts_vcf(contacts: list[dict], output_path: Path) -> int:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for contact in contacts:
        card = vobject.vCard()

        card.add("fn").value = contact["full_name"]

        # Split full_name into family/given best-effort
        parts = contact["full_name"].rsplit(" ", 1)
        n = card.add("n")
        n.value = vobject.vcard.Name(
            family=parts[-1] if len(parts) > 1 else parts[0],
            given=parts[0] if len(parts) > 1 else "",
        )

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
        vevent.add("dtstart", _parse_dt(ev["start"]))
        vevent.add("dtend", _parse_dt(ev["end"]))
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
