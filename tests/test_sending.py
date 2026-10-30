import smtplib
import threading

import pytest

from ptmail import mail_worker, smtp_client
from ptmail.accounts import Account
from ptmail.imap_client import ImapClient, ImapConnectionError
from ptmail.smtp_client import SmtpAuthError, SmtpRecipientError, send_mail

ICLOUD = Account("iCloud", "ja@icloud.com", "icloud")
GMAIL = Account("Gmail", "ja@gmail.com", "gmail")


class FakeSmtp:
    error = None
    sent = []

    def __init__(self, host, port, timeout):
        self.host = host

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def starttls(self, context):
        FakeSmtp.sent.append("starttls")

    def login(self, user, password):
        if FakeSmtp.error:
            raise FakeSmtp.error

    def sendmail(self, sender, recipients, raw):
        FakeSmtp.sent.append((self.host, sender, recipients))
        return {}


@pytest.fixture(autouse=True)
def fake_smtp(monkeypatch):
    FakeSmtp.error = None
    FakeSmtp.sent = []
    monkeypatch.setattr(smtp_client.smtplib, "SMTP", FakeSmtp)


def test_send_uses_starttls_before_sending():
    send_mail(ICLOUD, "x", ["a@b.pl"], b"raw")
    assert FakeSmtp.sent == [
        "starttls",
        ("smtp.mail.me.com", "ja@icloud.com", ["a@b.pl"]),
    ]


def test_smtp_errors_are_translated():
    FakeSmtp.error = smtplib.SMTPAuthenticationError(535, b"zle")
    with pytest.raises(SmtpAuthError):
        send_mail(ICLOUD, "x", ["a@b.pl"], b"raw")
    FakeSmtp.error = smtplib.SMTPRecipientsRefused({"a@b.pl": (550, b"nie")})
    with pytest.raises(SmtpRecipientError):
        send_mail(ICLOUD, "x", ["a@b.pl"], b"raw")


class FakeImap:
    def __init__(self):
        self.appended = []

    def list(self):
        return "OK", [
            b'(\\HasNoChildren) "/" "Sent Messages"',
            b'(\\HasNoChildren \\Drafts) "/" "Drafts"',
        ]

    def append(self, mailbox, flags, date_time, message):
        self.appended.append((mailbox, flags, message))
        return "OK", [b"done"]


def test_append_targets_folder_by_role():
    imap = FakeImap()
    client = ImapClient(ICLOUD, "x")
    client._imap = imap
    client.append("sent", "(\\Seen)", b"raw")
    assert imap.appended == [('"Sent Messages"', "(\\Seen)", b"raw")]


class FakeClient:
    def __init__(self, fail=False):
        self.connected = True
        self.fail = fail
        self.calls = []

    def close(self):
        pass

    def connect(self):
        pass

    def append(self, role, flags, raw):
        if self.fail:
            raise ImapConnectionError("zerwane")
        self.calls.append((role, flags))


def run(account, client, start):
    results = []
    done = threading.Event()

    def on_done(success, text):
        results.append((success, text))
        done.set()

    class Listener:
        def on_outgoing_done(self, callback, success, text):
            callback(success, text)

    worker = mail_worker.MailWorker(
        account, "x", Listener(), lambda _w, handler, *args: handler(*args)
    )
    worker._client = client
    worker.start()
    start(worker, on_done)
    assert done.wait(2)
    worker.stop()
    worker.join(2)
    return results


def send(worker, on_done):
    worker.send(["a@b.pl"], b"raw", on_done)


def test_icloud_saves_sent_copy():
    client = FakeClient()
    assert run(ICLOUD, client, send) == [(True, "Wysłano")]
    assert client.calls == [("sent", "(\\Seen)")]


def test_gmail_does_not_save_sent_copy():
    client = FakeClient()
    assert run(GMAIL, client, send) == [(True, "Wysłano")]
    assert client.calls == []


def test_failed_sent_copy_still_counts_as_sent():
    assert run(ICLOUD, FakeClient(fail=True), send) == [
        (True, "Wysłano, ale nie zapisano w folderze Wysłane")
    ]


def test_failed_send_keeps_window_open():
    FakeSmtp.error = OSError("brak sieci")
    assert run(ICLOUD, FakeClient(), send) == [
        (False, "Nie udało się wysłać wiadomości")
    ]


def test_save_draft():
    client = FakeClient()
    result = run(ICLOUD, client, lambda w, done: w.save_draft(b"raw", done))
    assert result == [(True, "Zapisano w roboczych")]
    assert client.calls == [("drafts", "(\\Draft \\Seen)")]
    failed = run(ICLOUD, FakeClient(fail=True), lambda w, done: w.save_draft(b"raw", done))
    assert failed == [(False, "Nie udało się zapisać w roboczych")]
