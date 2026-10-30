import socket
import threading

import pytest

from ptmail import idle_watcher
from ptmail.accounts import Account
from ptmail.idle_watcher import IdleWatcher
from ptmail.imap_client import (
    ImapAuthError,
    ImapClient,
    ImapConnectionError,
    ImapError,
)

ACCOUNT = Account("iCloud", "ja@example.com", "icloud")


class FakeImap:
    """Prawdziwa para gniazd: po drugiej stronie test udaje serwer."""

    def __init__(self):
        self.sock, self.server = socket.socketpair()
        self.sent = []

    def send(self, data):
        self.sent.append(data)
        for reply in self.replies.get(data, ()):
            self.server.sendall(reply)

    replies = {}


@pytest.fixture
def imap():
    fake = FakeImap()
    fake.replies = {
        b"PTIDLE IDLE\r\n": [b"+ idling\r\n"],
        b"DONE\r\n": [b"PTIDLE OK IDLE terminated\r\n"],
    }
    yield fake
    fake.sock.close()
    fake.server.close()


def client_with(imap):
    client = ImapClient(ACCOUNT, "x")
    client._imap = imap
    return client


def never():
    return False


def test_exists_ends_waiting_with_done(imap):
    imap.replies[b"PTIDLE IDLE\r\n"] = [b"+ idling\r\n* 12 EXISTS\r\n* 1 RECENT\r\n"]
    assert client_with(imap).wait_for_new_mail(5, never)
    assert imap.sent == [b"PTIDLE IDLE\r\n", b"DONE\r\n"]


def test_timeout_ends_quietly_and_restores_socket(imap):
    assert not client_with(imap).wait_for_new_mail(0, never)
    assert imap.sent == [b"PTIDLE IDLE\r\n", b"DONE\r\n"]
    assert imap.sock.gettimeout() == 30


def test_flag_changes_are_not_new_mail(imap, monkeypatch):
    monkeypatch.setattr("ptmail.imap_client.IDLE_POLL_SECONDS", 0.05)
    imap.replies[b"PTIDLE IDLE\r\n"] = [b"+ idling\r\n* 3 FETCH (FLAGS (\\Seen))\r\n"]
    assert not client_with(imap).wait_for_new_mail(0.2, never)


def test_mail_reported_around_idle_is_not_lost(imap):
    imap.replies[b"PTIDLE IDLE\r\n"] = [b"* 5 EXISTS\r\n+ idling\r\n"]
    assert client_with(imap).wait_for_new_mail(5, never)


def test_mail_reported_after_done_is_not_lost(imap):
    imap.replies[b"DONE\r\n"] = [b"* 6 EXISTS\r\nPTIDLE OK done\r\n"]
    assert client_with(imap).wait_for_new_mail(0, never)


def test_stop_ends_waiting_quickly(imap):
    stopped = threading.Event()
    stopped.set()
    assert not client_with(imap).wait_for_new_mail(60, stopped.is_set)


def test_server_refusing_idle_is_an_error(imap):
    imap.replies[b"PTIDLE IDLE\r\n"] = [b"PTIDLE BAD unknown command\r\n"]
    with pytest.raises(ImapError) as error:
        client_with(imap).wait_for_new_mail(5, never)
    assert not isinstance(error.value, ImapConnectionError)


def test_closed_connection_is_reported(imap):
    imap.replies[b"PTIDLE IDLE\r\n"] = [b"+ idling\r\n"]
    imap.server.shutdown(socket.SHUT_WR)
    with pytest.raises(ImapConnectionError):
        client_with(imap).wait_for_new_mail(5, never)


def test_bye_is_a_lost_connection(imap):
    imap.replies[b"PTIDLE IDLE\r\n"] = [b"+ idling\r\n* BYE dosc\r\n"]
    with pytest.raises(ImapConnectionError):
        client_with(imap).wait_for_new_mail(5, never)


class FakeClient:
    """Skrypt kolejnych połączeń: lista wyników wait_for_new_mail lub wyjątków."""

    scripts = []
    instances = []

    def __init__(self, account, password):
        self.script = list(FakeClient.scripts.pop(0))
        self.closed = False
        FakeClient.instances.append(self)

    def connect(self):
        if self.script and isinstance(self.script[0], ImapAuthError):
            raise self.script[0]

    def select_for_idle(self, folder):
        assert folder == "INBOX"

    def wait_for_new_mail(self, seconds, stopped):
        if not self.script:
            watcher.stop()
            return False
        result = self.script.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def close(self):
        self.closed = True


watcher = None


def run_watcher(monkeypatch, scripts):
    global watcher
    FakeClient.scripts = scripts
    FakeClient.instances = []
    monkeypatch.setattr(idle_watcher, "ImapClient", FakeClient)
    monkeypatch.setattr(idle_watcher, "RECONNECT_SECONDS", 0)
    calls = []
    watcher = IdleWatcher(ACCOUNT, "x", lambda: calls.append("odswiez"))
    watcher.start()
    watcher.join(2)
    assert not watcher.is_alive()
    return calls


def test_watcher_reports_each_new_mail(monkeypatch):
    assert run_watcher(monkeypatch, [[True, False, True]]) == ["odswiez", "odswiez"]
    assert FakeClient.instances[0].closed


def test_watcher_catches_up_after_reconnecting(monkeypatch):
    calls = run_watcher(monkeypatch, [[ImapConnectionError("x")], []])
    assert calls == ["odswiez"]
    assert len(FakeClient.instances) == 2
    assert FakeClient.instances[0].closed


def test_watcher_gives_up_after_wrong_password(monkeypatch):
    calls = run_watcher(monkeypatch, [[ImapAuthError("x")], []])
    assert calls == []
    assert len(FakeClient.instances) == 1
