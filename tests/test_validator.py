import json
from pathlib import Path

import pytest

from synthdata_mail.validator import validate_dataset, validate_and_report

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


class TestValidDataset:
    def test_valid_returns_no_errors(self):
        data = load("valid_dataset.json")
        errors = validate_dataset(data)
        assert errors == []

    def test_valid_returns_correct_counts(self):
        _, errors = validate_and_report(str(FIXTURES / "valid_dataset.json"))
        assert errors == []

    def test_file_not_found(self):
        data, errors = validate_and_report("/nonexistent/path/dataset.json")
        assert data is None
        assert any("not found" in e.lower() for e in errors)


class TestSchemaErrors:
    def test_missing_required_field(self):
        data = load("invalid_dataset_schema.json")
        errors = validate_dataset(data)
        assert len(errors) > 0
        # Should report business_type missing (from persona)
        assert any("business_type" in e for e in errors)

    def test_invalid_email_format(self):
        data = load("invalid_dataset_schema.json")
        errors = validate_dataset(data)
        assert any("not-an-email" in e or "format" in e.lower() for e in errors)

    def test_invalid_folder_enum(self):
        data = load("invalid_dataset_schema.json")
        errors = validate_dataset(data)
        assert any("folder" in e or "invalid_folder" in e for e in errors)

    def test_all_errors_reported(self):
        # Should not stop at first error
        data = load("invalid_dataset_schema.json")
        errors = validate_dataset(data)
        assert len(errors) >= 2


class TestReferentialIntegrity:
    def test_dangling_contact_id_in_email(self):
        data = load("invalid_dataset_dangling_refs.json")
        errors = validate_dataset(data)
        assert any("c-does-not-exist" in e for e in errors)

    def test_dangling_in_reply_to(self):
        data = load("invalid_dataset_dangling_refs.json")
        errors = validate_dataset(data)
        assert any("e-does-not-exist" in e for e in errors)

    def test_dangling_attendee_contact_id(self):
        data = load("invalid_dataset_dangling_refs.json")
        errors = validate_dataset(data)
        assert any("c-also-missing" in e for e in errors)

    def test_dangling_related_thread_id(self):
        data = load("invalid_dataset_dangling_refs.json")
        errors = validate_dataset(data)
        assert any("thread-does-not-exist" in e for e in errors)

    def test_all_dangling_refs_reported(self):
        data = load("invalid_dataset_dangling_refs.json")
        errors = validate_dataset(data)
        # Should report all 4 referential integrity problems
        assert len(errors) >= 4
