import queue
import threading
from dataclasses import dataclass

from .i18n import _
from .imap_client import ImapAuthError, ImapClient, ImapConnectionError, ImapError
from .message_parser import parse_message

INBOX = "INBOX"
RETRY_SECONDS = 60


@dataclass(frozen=True)
class Request:
    folder: str
    with_folders: bool


@dataclass(frozen=True)
class OpenMessage:
    folder: str
    uid: int


class MailWorker(threading.Thread):
    """Jedyny wątek rozmawiający z serwerem, bo połączenia IMAP nie wolno współdzielić.

    Wyniki trafiają do listenera przez dispatch, który przenosi je do wątku interfejsu.
    """

    def __init__(self, account, password, listener, dispatch):
        super().__init__(daemon=True)
        self._account = account
        self._client = ImapClient(account, password)
        self._listener = listener
        self._dispatch = dispatch
        self._requests = queue.Queue()
        self._stopped = threading.Event()
        self._error_reported = False

    def refresh(self, folder):
        self._requests.put(Request(folder, with_folders=True))

    def open_folder(self, folder):
        self._requests.put(Request(folder, with_folders=False))

    def open_message(self, folder, uid):
        self._requests.put(OpenMessage(folder, uid))

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
        self._emit(self._listener.on_messages, request.folder, messages)
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
