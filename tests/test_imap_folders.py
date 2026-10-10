"""Tests for IMAP folder resolution and batch reset search criteria."""
from types import SimpleNamespace

import pytest

from synthdata_mail import reset_client
from synthdata_mail.imap_client import _resolve_folder


def make_folder(name: str, delim: str = "/", flags: tuple = ()) -> SimpleNamespace:
    return SimpleNamespace(name=name, delim=delim, flags=flags)


def make_mailbox(folders: list) -> SimpleNamespace:
    return SimpleNamespace(folder=SimpleNamespace(list=lambda: folders))


# Folder layout reported by a server with no special-use flags and a "mail/" prefix
PREFIXED_FOLDERS = [
    make_folder("INBOX", delim="NIL", flags=("\\NoInferiors",)),
    make_folder("mail/drafts", flags=("\\UnMarked",)),
    make_folder("mail/SPAM.incoming", flags=("\\UnMarked",)),
    make_folder("mail/sent-mail", flags=("\\Marked",)),
    make_folder("mail/trash", flags=("\\UnMarked",)),
]


class TestResolveFolder:
    def test_inbox(self):
        assert _resolve_folder(make_mailbox([]), "inbox") == "INBOX"

    def test_special_use_flag_preferred(self):
        mb = make_mailbox([make_folder("Sent"), make_folder("Gesendet", flags=("\\Sent",))])
        assert _resolve_folder(mb, "sent") == "Gesendet"

    def test_exact_literal_name(self):
        mb = make_mailbox([make_folder("Sent Items"), make_folder("Drafts")])
        assert _resolve_folder(mb, "sent") == "Sent Items"
        assert _resolve_folder(mb, "drafts") == "Drafts"

    def test_prefixed_leaf_names(self):
        mb = make_mailbox(PREFIXED_FOLDERS)
        assert _resolve_folder(mb, "sent") == "mail/sent-mail"
        assert _resolve_folder(mb, "drafts") == "mail/drafts"

    def test_dot_delimited_leaf_case_insensitive(self):
        mb = make_mailbox([make_folder("INBOX.sent", delim="."), make_folder("INBOX.DRAFTS", delim=".")])
        assert _resolve_folder(mb, "sent") == "INBOX.sent"
        assert _resolve_folder(mb, "drafts") == "INBOX.DRAFTS"

    def test_unresolvable_raises_with_available_folders(self):
        mb = make_mailbox([make_folder("mail/trash")])
        with pytest.raises(ValueError, match="mail/trash"):
            _resolve_folder(mb, "sent")


class FakeResetMailBox:
    """Minimal stand-in for imap_tools.MailBox used by reset_by_batch_id."""

    def __init__(self, server):
        self.criteria = []
        self.stored = []
        self.folder = SimpleNamespace(list=lambda: PREFIXED_FOLDERS, set=lambda name: None)
        self.client = SimpleNamespace(
            capability=lambda: ("OK", [b"IMAP4rev1 UIDPLUS"]),
            uid=lambda *args: self.stored.append(args),
            expunge=lambda: None,
        )

    def login(self, username, password):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def fetch(self, criteria, **kwargs):
        self.criteria.append(str(criteria))
        return [SimpleNamespace(uid="7")]


class TestResetByBatchId:
    def test_searches_batch_header_and_removes_matches(self, monkeypatch):
        boxes = []

        def factory(server):
            boxes.append(FakeResetMailBox(server))
            return boxes[-1]

        monkeypatch.setattr(reset_client.imap_tools, "MailBox", factory)
        monkeypatch.setattr(reset_client, "_throttle", lambda *a: None)

        counts = reset_client.reset_by_batch_id(
            server="imap.example.com",
            username="user@example.com",
            password="secret",
            batch_id="batch-123",
            delay_min=0,
            delay_max=0,
        )

        mb = boxes[0]
        assert mb.criteria
        assert all('HEADER "X-WM8-Seed-Batch" "batch-123"' in c for c in mb.criteria)
        assert counts == {"inbox": 1, "sent": 1, "drafts": 1}
