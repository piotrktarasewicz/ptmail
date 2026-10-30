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

Przy pierwszym uruchomieniu program prosi o konto: adres i hasło aplikacji. Hasło trafia do Menedżera poświadczeń Windows, a nazwa i adres do `%APPDATA%\PT Mail\config.json`.

## Testy

```bash
.venv\Scripts\python -m pytest
```

## Struktura

| Plik | Rola |
| --- | --- |
| `ptmail/app.py` | start programu |
| `ptmail/ui/` | okno główne, listy, okno konta |
| `ptmail/mail_worker.py` | wątek w tle, jedyne miejsce używające połączenia IMAP |
| `ptmail/imap_client.py` | operacje IMAP |
| `ptmail/imap_parser.py` | parsowanie odpowiedzi serwera, bez sieci |
| `ptmail/formatting.py` | zdania czytane przez NVDA |
| `ptmail/accounts.py`, `config.py`, `credentials.py` | konto, konfiguracja, hasło |
| `ptmail/i18n.py` | tłumaczenia (gettext) |
