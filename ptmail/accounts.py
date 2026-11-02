from dataclasses import dataclass

from .i18n import _


@dataclass(frozen=True)
class Provider:
    key: str
    label: str
    imap_host: str
    imap_port: int
    smtp_host: str
    smtp_port: int
    saves_sent: bool  # czy serwer sam odkłada wysłaną pocztę do Wysłanych
    archive_by_label: bool  # czy archiwizacja to zdjęcie etykiety Odebrane
    supports_move: bool = True  # bez MOVE przenosimy przez kopiowanie i usunięcie
    uses_xlist: bool = False  # role folderów podaje tylko starsze polecenie XLIST
    app_password: bool = True  # logowanie osobnym hasłem aplikacji, a nie hasłem konta
    login_hint: str = ""  # co sprawdzić, gdy serwer odrzuci logowanie


PROVIDERS = {
    "gmail": Provider(
        "gmail", "Gmail", "imap.gmail.com", 993, "smtp.gmail.com", 587, True, True
    ),
    "icloud": Provider(
        "icloud",
        "iCloud",
        "imap.mail.me.com",
        993,
        "smtp.mail.me.com",
        587,
        False,
        False,
    ),
    "interia": Provider(
        "interia",
        "Interia",
        "poczta.interia.pl",
        993,
        "poczta.interia.pl",
        587,
        False,
        False,
        supports_move=False,
        uses_xlist=True,
        app_password=False,
        login_hint=_("Sprawdź, czy w ustawieniach poczty Interia włączony jest dostęp dla programów pocztowych"),
    ),
}


@dataclass(frozen=True)
class Account:
    name: str
    email: str
    provider_key: str
    display_name: str = ""  # imię i nazwisko widoczne u adresata
    signature: str = ""

    @property
    def provider(self):
        return PROVIDERS[self.provider_key]
