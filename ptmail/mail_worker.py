import queue
import threading
from collections.abc import Callable
from dataclasses import dataclass

from .i18n import _
from .imap_client import ImapAuthError, ImapClient, ImapConnectionError, ImapError
from .message_parser import parse_message
from .smtp_client import SmtpAuthError, SmtpError, SmtpRecipientError, send_mail

INBOX = "INBOX"
RETRY_SECONDS = 60


@dataclass(frozen=True)
class Request:
    folder: str
    with_folders: bool
    silent: bool = False


@dataclass(frozen=True)
class OpenMessage:
    folder: str
    uid: int


@dataclass(frozen=True)
class MessageAction:
    run: Callable[[ImapClient], None]
    failure_text: str


@dataclass(frozen=True)
class SendMail:
    recipients: tuple[str, ...]
    raw: bytes
    on_done: Callable[[bool, str], None]


@dataclass(frozen=True)
class SaveDraft:
    raw: bytes
    on_done: Callable[[bool, str], None]


class MailWorker(threading.Thread):
    """Jedyny wątek rozmawiający z serwerem, bo połączenia IMAP nie wolno współdzielić.

    Wyniki trafiają do listenera przez dispatch, który przenosi je do wątku interfejsu.
    """

    def __init__(self, account, password, listener, dispatch):
        super().__init__(daemon=True)
        self._account = account
        self._password = password
        self._client = ImapClient(account, password)
        self._listener = listener
        self._dispatch = dispatch
        self._requests = queue.Queue()
        self._stopped = threading.Event()
        self._error_reported = False

    def refresh(self, folder, silent=False):
        self._requests.put(Request(folder, with_folders=True, silent=silent))

    def perform(self, run, failure_text):
        """Zleca czynność na wiadomości. Okno pokazało już jej skutek."""
        self._requests.put(MessageAction(run, failure_text))

    def refresh_inbox_silently(self):
        """Odświeżenie zgłoszone przez serwer: bez dźwięku, jeśli nic nowego nie ma."""
        self._requests.put(Request(INBOX, with_folders=True, silent=True))

    def open_folder(self, folder):
        self._requests.put(Request(folder, with_folders=False))

    def open_message(self, folder, uid):
        self._requests.put(OpenMessage(folder, uid))

    def send(self, recipients, raw, on_done):
        self._requests.put(SendMail(tuple(recipients), raw, on_done))

    def save_draft(self, raw, on_done):
        self._requests.put(SaveDraft(raw, on_done))

    def stop(self):
        self._stopped.set()
        self._requests.put(None)

    def run(self):
        retry = None
        while not self._stopped.is_set():
            try:
                timeout = RETRY_SECONDS if retry is not None else None
                request = self._requests.get(timeout=timeout)
            except queue.Empty:
                request = retry
            if isinstance(request, OpenMessage):
                # Bez ponawiania: otwarcie po minucie przesunęłoby fokus bez działania użytkownika.
                self._open_message(request)
            elif isinstance(request, MessageAction):
                self._perform(request)
            elif isinstance(request, SendMail):
                self._send(request)
            elif isinstance(request, SaveDraft):
                self._save_draft(request)
            elif request is not None:
                retry = self._process(request)
        self._client.close()

    def _process(self, request):
        """Obsługuje żądanie. Zwraca je z powrotem, gdy trzeba ponowić próbę."""
        try:
            self._sync(request)
        except ImapConnectionError:
            self._client.close()
            self._report(
                _("Brak połączenia z {name}, spróbuję ponownie").format(
                    name=self._account.name
                )
            )
            return request
        except ImapAuthError:
            self._client.close()
            self._report(
                _("Logowanie do {name} nie powiodło się").format(
                    name=self._account.name
                )
            )
        except ImapError:
            self._report(_("Nie udało się pobrać poczty z {name}").format(
                name=self._account.name
            ))
        return None

    def _sync(self, request):
        if request.with_folders:
            folders = self._with_client(self._client.list_folders)
            self._emit(self._listener.on_folders, folders)
        messages = self._with_client(self._client.fetch_recent, request.folder)
        self._emit(
            self._listener.on_messages,
            request.folder,
            messages,
            request.with_folders,
            request.silent,
        )
        self._error_reported = False

    def _open_message(self, request):
        try:
            raw = self._with_client(
                self._client.fetch_message, request.folder, request.uid
            )
        except ImapError:
            self._client.close()
            self._emit(self._listener.on_open_failed, request.folder, request.uid)
            return
        self._emit(
            self._listener.on_message_opened,
            request.folder,
            request.uid,
            parse_message(raw),
        )

    def _perform(self, request):
        try:
            self._with_client(request.run, self._client)
        except ImapError:
            self._client.close()
            self._emit(self._listener.on_action_failed, request.failure_text)

    def _send(self, request):
        try:
            refused = send_mail(
                self._account, self._password, request.recipients, request.raw
            )
        except SmtpAuthError:
            self._finish(request, False, _("Serwer odrzucił hasło aplikacji"))
            return
        except SmtpRecipientError:
            self._finish(request, False, _("Serwer odrzucił adres odbiorcy"))
            return
        except SmtpError:
            self._finish(request, False, _("Nie udało się wysłać wiadomości"))
            return
        if refused:
            text = _("Wysłano, ale serwer odrzucił część odbiorców")
        else:
            text = _("Wysłano")
        if not self._account.provider.saves_sent and not self._append(
            "sent", "(\\Seen)", request.raw
        ):
            text = _("Wysłano, ale nie zapisano w folderze Wysłane")
        self._finish(request, True, text)

    def _save_draft(self, request):
        if self._append("drafts", "(\\Draft \\Seen)", request.raw):
            self._finish(request, True, _("Zapisano w roboczych"))
        else:
            self._finish(request, False, _("Nie udało się zapisać w roboczych"))

    def _append(self, role, flags, raw):
        try:
            self._with_client(self._client.append, role, flags, raw)
        except ImapError:
            self._client.close()
            return False
        return True

    def _finish(self, request, success, text):
        self._emit(self._listener.on_outgoing_done, request.on_done, success, text)

    def _with_client(self, action, *args):
        """Wykonuje działanie, a gdy serwer zerwał bezczynne połączenie, łączy się raz od nowa."""
        if not self._client.connected:
            self._client.connect()
        try:
            return action(*args)
        except ImapConnectionError:
            self._client.close()
            self._client.connect()
            return action(*args)

    def _report(self, text):
        if not self._error_reported:
            self._error_reported = True
            self._emit(self._listener.on_error, text)

    def _emit(self, handler, *args):
        if not self._stopped.is_set():
            self._dispatch(self, handler, *args)
