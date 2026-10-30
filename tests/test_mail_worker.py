import threading

from ptmail.accounts import Account
from ptmail.imap_client import ImapConnectionError
from ptmail.mail_worker import MailWorker

RAW = b"From: a@b.pl\r\nSubject: x\r\n\r\ntresc"


class FakeClient:
    def __init__(self, failures):
        self.failures = failures
        self.connected = False
        self.connections = 0

    def connect(self):
        self.connected = True
        self.connections += 1

    def close(self):
        self.connected = False

    def fetch_message(self, folder, uid):
        if self.failures:
            self.failures -= 1
            raise ImapConnectionError("zerwane")
        return RAW


class Listener:
    def __init__(self):
        self.results = []
        self.done = threading.Event()

    def on_message_opened(self, folder, uid, content):
        self.results.append((uid, content.body))
        self.done.set()

    def on_open_failed(self, folder, uid):
        self.results.append("failed")
        self.done.set()


def open_message(client):
    listener = Listener()
    worker = MailWorker(
        Account("iCloud", "a@example.com", "icloud"),
        "x",
        listener,
        lambda _worker, handler, *args: handler(*args),
    )
    worker._client = client
    worker.start()
    worker.open_message("INBOX", 7)
    assert listener.done.wait(2)
    worker.stop()
    worker.join(2)
    return listener.results


def test_dropped_connection_is_restored_once():
    client = FakeClient(failures=1)
    assert open_message(client) == [(7, "tresc")]
    assert client.connections == 2


def test_failed_open_is_reported_without_retry():
    assert open_message(FakeClient(failures=2)) == ["failed"]
