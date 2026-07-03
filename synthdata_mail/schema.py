DATASET_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "SynthDataMailDataset",
    "type": "object",
    "required": ["persona", "contacts", "emails", "events"],
    "properties": {
        "persona": {
            "type": "object",
            "required": ["business_name", "business_type"],
            "properties": {
                "business_name": {"type": "string"},
                "business_type": {"type": "string"},
            },
        },
        "contacts": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["contact_id", "full_name", "email", "role"],
                "properties": {
                    "contact_id": {"type": "string"},
                    "full_name": {"type": "string"},
                    "email": {"type": "string", "format": "email"},
                    "company": {"type": "string"},
                    "role": {"type": "string"},
                    "phone": {"type": "string"},
                },
            },
        },
        "emails": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["email_id", "folder", "contact_id", "direction", "subject", "body", "timestamp", "read"],
                "properties": {
                    "email_id": {"type": "string"},
                    "folder": {"type": "string", "enum": ["inbox", "sent", "drafts"]},
                    "contact_id": {"type": "string"},
                    "direction": {"type": "string", "enum": ["incoming", "outgoing"]},
                    "subject": {"type": "string"},
                    "body": {"type": "string"},
                    "timestamp": {"type": "string", "format": "date-time"},
                    "read": {"type": "boolean"},
                    "thread_id": {"type": "string"},
                    "in_reply_to_email_id": {"type": "string"},
                },
            },
        },
        "events": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["event_id", "title", "start", "end", "attendee_contact_ids"],
                "properties": {
                    "event_id": {"type": "string"},
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "start": {"type": "string", "format": "date-time"},
                    "end": {"type": "string", "format": "date-time"},
                    "attendee_contact_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "related_email_thread_id": {"type": "string"},
                },
            },
        },
    },
}

CUSTOM_EMAIL_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "CustomEmailDescriptor",
    "type": "object",
    "required": ["subject", "from_name", "from_email", "html_file"],
    "properties": {
        "subject": {"type": "string"},
        "from_name": {"type": "string"},
        "from_email": {"type": "string", "format": "email"},
        "html_file": {"type": "string"},
    },
}
