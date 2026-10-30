"""Zamiana surowej wiadomości na tekst, linki i załączniki. Bez sieci."""

import email
import re
from email.utils import getaddresses
from html.parser import HTMLParser
from urllib.parse import urlsplit

from .i18n import _
from .imap_parser import decode_header_text, parse_date
from .models import Attachment, Link, MessageContent

SKIPPED_TAGS = {"script", "style", "head", "title"}
BLOCK_TAGS = {
    "address", "blockquote", "div", "footer", "h1", "h2", "h3", "h4", "h5", "h6",
    "header", "hr", "li", "ol", "p", "pre", "section", "table", "tr", "ul",
}
LINK_SCHEMES = ("http://", "https://", "mailto:")
# Znaki z obszaru prywatnego Unicode oznaczają granice linków podczas
# porządkowania tekstu, które zmienia pozycje znaków.
LINK_OPEN = ""
LINK_CLOSE = ""
TEXT_URL_RE = re.compile(r"<?(https?://[^\s<>\"]+)>?", re.IGNORECASE)
ADDRESS_LIKE_RE = re.compile(r"(https?://|www\.)\S+$", re.IGNORECASE)
ADDRESS_LIKE_LENGTH = 40


def link_host(url):
    if url.lower().startswith("mailto:"):
        return url[len("mailto:"):]
    try:
        return (urlsplit(url).hostname or "").removeprefix("www.")
    except ValueError:
        return ""


def _link_label(url):
    host = link_host(url)
    return _("link {host}").format(host=host) if host else _("link")


def _is_address(text):
    if " " in text:
        return False
    return bool(ADDRESS_LIKE_RE.match(text)) or len(text) > ADDRESS_LIKE_LENGTH


def _strip_markers(text):
    return text.replace(LINK_OPEN, "").replace(LINK_CLOSE, "")


class _HtmlText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.urls = []
        self._skipped = 0
        self._href = None
        self._link_start = 0

    def handle_starttag(self, tag, attrs):
        if tag in SKIPPED_TAGS:
            self._skipped += 1
        elif tag == "br" or tag in BLOCK_TAGS:
            self.parts.append("\n")
        elif tag == "a":
            self._href = dict(attrs).get("href") or ""
            self._link_start = len(self.parts)
        elif tag == "img" and self._href is not None:
            # Obrazki pomijamy, chyba że są linkiem i mają opis.
            self.parts.append(_strip_markers(dict(attrs).get("alt") or ""))

    def handle_endtag(self, tag):
        if tag in SKIPPED_TAGS:
            self._skipped = max(0, self._skipped - 1)
        elif tag in BLOCK_TAGS:
            self.parts.append("\n")
        elif tag == "td":
            self.parts.append(" ")
        elif tag == "a":
            self._close_link()

    def handle_data(self, data):
        if not self._skipped:
            self.parts.append(re.sub(r"\s+", " ", _strip_markers(data)))

    def _close_link(self):
        href, self._href = self._href, None
        if href is None:
            return
        url = "".join(href.split())
        if not url.lower().startswith(LINK_SCHEMES):
            return
        text = " ".join("".join(self.parts[self._link_start:]).split())
        del self.parts[self._link_start:]
        if text:
            label = _link_label(url) if _is_address(text) else text
            self.parts.append(f"{LINK_OPEN}{label}{LINK_CLOSE}")
            self.urls.append(url)


def html_to_text(html):
    """Zwraca czysty tekst i krotkę linków z pozycjami w tym tekście."""
    parser = _HtmlText()
    parser.feed(html)
    parser.close()
    lines = [line.strip() for line in "".join(parser.parts).split("\n")]
    marked = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return _resolve_links(marked, parser.urls)


def linkify_text(text):
    """Zamienia gołe adresy w tekście na krótkie etykiety linków."""
    urls = []

    def replace(match):
        url = match.group(1).rstrip(".,;:!?)]'")
        urls.append(url)
        trailing = match.group(1)[len(url):]
        return f"{LINK_OPEN}{_link_label(url)}{LINK_CLOSE}{trailing}"

    return _resolve_links(TEXT_URL_RE.sub(replace, _strip_markers(text)), urls)


def _resolve_links(marked, urls):
    pieces = []
    spans = []
    length = 0
    start = 0
    for piece in re.split(f"([{LINK_OPEN}{LINK_CLOSE}])", marked):
        if piece == LINK_OPEN:
            start = length
        elif piece == LINK_CLOSE:
            spans.append((start, length))
        else:
            pieces.append(piece)
            length += len(piece)
    text = "".join(pieces)
    links = tuple(
        Link(start, end, url, text[start:end])
        for (start, end), url in zip(spans, urls)
    )
    return text, links


def parse_message(raw):
    message = email.message_from_bytes(raw)
    plain = None
    html = None
    attachments = []
    for part in message.walk():
        if part.is_multipart():
            continue
        if _is_attachment(part):
            attachments.append(_attachment(part))
        elif part.get_content_type() == "text/plain" and plain is None:
            plain = part
        elif part.get_content_type() == "text/html" and html is None:
            html = part
    body, links = _body(plain, html)
    return MessageContent(
        sender=decode_header_text(message.get("From", "")),
        recipients=decode_header_text(message.get("To", "")),
        subject=decode_header_text(message.get("Subject", "")),
        date=parse_date(message.get("Date")),
        body=body,
        attachments=tuple(attachments),
        links=links,
        from_addresses=_addresses(message, "From"),
        reply_to_addresses=_addresses(message, "Reply-To"),
        to_addresses=_addresses(message, "To"),
        cc_addresses=_addresses(message, "Cc"),
        message_id=str(message.get("Message-ID", "")).strip(),
        references=" ".join(str(message.get("References", "")).split()),
    )


def _addresses(message, header):
    values = [str(value) for value in message.get_all(header, [])]
    return tuple(
        (decode_header_text(name), address)
        for name, address in getaddresses(values)
        if address
    )


def _is_attachment(part):
    disposition = part.get_content_disposition()
    if disposition == "attachment":
        return True
    # Obrazki wstawione w treść, np. logo w stopce, to nie załączniki.
    if part.get("Content-ID"):
        return False
    return part.get_filename() is not None


def _attachment(part):
    filename = decode_header_text(part.get_filename() or "") or _("załącznik")
    return Attachment(
        filename, part.get_content_type(), part.get_payload(decode=True) or b""
    )


def _body(plain, html):
    # HTML ma pierwszeństwo, bo tylko on zawiera opisy linków.
    if html is not None:
        text, links = html_to_text(_text(html))
        if text:
            return text, links
    if plain is not None:
        return linkify_text(_text(plain).strip())
    return "", ()


def _text(part):
    payload = part.get_payload(decode=True) or b""
    try:
        text = payload.decode(part.get_content_charset() or "utf-8", "replace")
    except LookupError:
        text = payload.decode("utf-8", "replace")
    return text.replace("\r\n", "\n")
