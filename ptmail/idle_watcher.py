import threading

from .imap_client import ImapClient, ImapConnectionError, ImapError

INBOX = "INBOX"
# Serwery zrywają IDLE po mniej niż 30 minutach, a częstsze wznawianie szybciej
# wykrywa martwe połączenie, np. po uśpieniu komputera.
IDLE_SECONDS = 9 * 60
RECONNECT_SECONDS = 60


class IdleWatcher(threading.Thread):
    """Trzyma osobne połączenie, na którym serwer sam zgłasza nową pocztę w Odebranych.

    Błędy są ciche, bo komunikaty o połączeniu należą do MailWorkera.
    """

    def __init__(self, account, password, on_new_mail):
        super().__init__(daemon=True)
        self._account = account
        self._password = password
        self._on_new_mail = on_new_mail
        self._stopped = threading.Event()

    def stop(self):
        self._stopped.set()

    def run(self):
        reconnecting = False
        while not self._stopped.is_set():
            client = ImapClient(self._account, self._password)
            try:
                client.connect()
                client.select_for_idle(INBOX)
                if reconnecting:
                    # Poczta mogła przyjść, gdy połączenia nie było.
                    self._on_new_mail()
                self._watch(client)
            except ImapConnectionError:
                reconnecting = True
            except ImapError:
                # Złe hasło albo brak IDLE: ponawianie niczego nie zmieni.
                return
            finally:
                client.close()
            self._stopped.wait(RECONNECT_SECONDS)

    def _watch(self, client):
        while not self._stopped.is_set():
            if client.wait_for_new_mail(IDLE_SECONDS, self._stopped.is_set):
                self._on_new_mail()
