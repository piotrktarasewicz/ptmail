from dataclasses import dataclass


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
}


@dataclass(frozen=True)
class Account:
    name: str
    email: str
    provider_key: str
    display_name: str = ""  # imię i nazwisko widoczne u adresata

    @property
    def provider(self):
        return PROVIDERS[self.provider_key]
