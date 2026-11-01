"""Podpowiadanie adresów z wysłanej poczty. Bez sieci."""

import email
import re
from email.utils import getaddresses

from .compose import ADDRESS_RE, display_address
from .i18n import _
from .imap_parser import decode_header_text
from .models import Contact

MIN_FRAGMENT_LENGTH = 2
SUGGESTION_LIMIT = 10
# Takiej nazwy nie da się bezpiecznie wstawić do pola Do, a adres w nazwie nic nie wnosi.
UNUSABLE_NAME_RE = re.compile(r'[@";<>()]')


def _usable_name(name):
    name = decode_header_text(name)
    return "" if UNUSABLE_NAME_RE.search(name) else name


def parse_contacts(text):
    """Zwraca kontakty z pola Do lub DW, pomijając to, co adresem nie jest."""
    return _contacts_from([text.replace(";", ",")])


def _contacts_from(values):
    pairs = getaddresses(values)
    return [
        Contact(_usable_name(name), address.lower())
        for name, address in pairs
        if ADDRESS_RE.match(address) and address.isascii()
    ]


def contacts_from_headers(blocks):
    """Zlicza adresatów z nagłówków wysłanych wiadomości, od najstarszej."""
    contacts = []
    for block in blocks:
        parsed = email.message_from_bytes(block)
        values = [str(parsed.get(field, "")) for field in ("To", "Cc")]
        contacts += _contacts_from([value for value in values if value])
    return merge_contacts(contacts)


def merge_contacts(contacts):
    """Łączy powtórzenia. Najczęściej używane idą na początek, a nazwa z najnowszego."""
    merged = {}
    for contact in contacts:
        known = merged.get(contact.address)
        if known is None:
            merged[contact.address] = contact
        else:
            merged[contact.address] = Contact(
                contact.name or known.name,
                contact.address,
                known.uses + contact.uses,
            )
    return sorted(merged.values(), key=lambda contact: -contact.uses)


def current_fragment(text, caret):
    """Zwraca początek i koniec adresu, przy którym stoi kursor."""
    start = max(text.rfind(",", 0, caret), text.rfind(";", 0, caret)) + 1
    ends = [found for found in (text.find(",", caret), text.find(";", caret)) if found >= 0]
    end = min(ends, default=len(text))
    while start < end and text[start] == " ":
        start += 1
    return start, end


def _matches(contact, wanted):
    name = contact.name.casefold()
    words = (contact.address, name, *name.split())
    return any(word.startswith(wanted) for word in words)


def matching_contacts(contacts, fragment):
    wanted = fragment.strip().casefold()
    if len(wanted) < MIN_FRAGMENT_LENGTH:
        return []
    return [c for c in contacts if _matches(c, wanted)][:SUGGESTION_LIMIT]


def insert_contact(text, start, end, contact):
    """Wstawia adres w miejsce fragmentu. Zwraca nowy tekst i pozycję kursora."""
    inserted = f"{text[:start]}{display_address(contact.name, contact.address)}, "
    return inserted + text[end:].lstrip(",; "), len(inserted)


def suggestion_sentence(contact, index, count):
    text = f"{contact.name}, {contact.address}" if contact.name else contact.address
    if count > 1:
        position = _("{index} z {count}").format(index=index + 1, count=count)
        return f"{text}, {position}"
    return text
