# PT Mail

Prosty klient poczty na Windows dla jednego użytkownika pracującego z NVDA. Pełna specyfikacja: [docs/SPEC.md](docs/SPEC.md).

## Uruchomienie

Potrzebny jest Python 3.11 lub nowszy.

```bash
python -m venv .venv
```

```bash
.venv\Scripts\python -m pip install -e .[dev]
```

```bash
.venv\Scripts\python -m ptmail
```

Przy pierwszym uruchomieniu program prosi o konto: adres i hasło aplikacji. Kolejne konta dodaje się w menu Plik, Konta. Hasła trafiają do Menedżera poświadczeń Windows, a nazwy i adresy do `%APPDATA%\PT Mail\config.json`.

## Testy

```bash
.venv\Scripts\python -m pytest
```

## Struktura

| Plik | Rola |
| --- | --- |
| `ptmail/app.py` | start programu |
| `ptmail/ui/` | okno główne, listy, widok wiadomości, okno konta |
| `ptmail/cache.py` | pamięć podręczna SQLite |
| `ptmail/mail_worker.py` | wątek w tle, jedyne miejsce używające połączenia IMAP |
| `ptmail/idle_watcher.py` | osobne połączenie IDLE, które zgłasza nową pocztę |
| `ptmail/imap_client.py` | operacje IMAP |
| `ptmail/imap_parser.py` | parsowanie odpowiedzi serwera, bez sieci |
| `ptmail/message_parser.py` | treść i załączniki z surowej wiadomości, HTML na czysty tekst |
| `ptmail/compose.py` | szkice: nowa, odpowiedź, przekazanie, budowa maila |
| `ptmail/smtp_client.py` | wysyłka SMTP |
| `ptmail/attachments.py` | zapisywanie i otwieranie załączników |
| `ptmail/formatting.py` | zdania czytane przez NVDA i tekst wiadomości |
| `ptmail/speech.py` | komunikaty mówione przez NVDA |
| `ptmail/sounds.py` | dźwięki pobrania i nowej poczty |
| `ptmail/accounts.py`, `config.py`, `credentials.py` | konto, konfiguracja, hasło |
| `ptmail/i18n.py` | tłumaczenia (gettext) |
