"""Szkice wiadomości: nowa, odpowiedź, przekazanie i budowa gotowego maila. Bez sieci."""

import mimetypes
import re
from dataclasses import dataclass, replace
from email.message import EmailMessage
from email.policy import SMTP
from email.utils import formataddr, formatdate, getaddresses, make_msgid
from pathlib import Path

from .i18n import _
from .models import Attachment

ADDRESS_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+$")
REPLY_PREFIX_RE = re.compile(r"(re|odp)\s*:", re.IGNORECASE)
FORWARD_PREFIX_RE = re.compile(r"(fwd?|pd)\s*:", re.IGNORECASE)


@dataclass(frozen=True)
class Draft:
    sender: str = ""  # adres konta, z którego idzie wiadomość
    to: str = ""
    cc: str = ""
    subject: str = ""
    body: str = ""
    attachments: tuple[Attachment, ...] = ()
    in_reply_to: str = ""
    references: str = ""
    focus_body: bool = False


def display_address(name, address):
    if not name:
        return address
    return f'"{name}" <{address}>' if "," in name else f"{name} <{address}>"


def _join(addresses):
    return ", ".join(display_address(name, address) for name, address in addresses)


def _unique(addresses, excluded):
    seen = set(excluded)
    result = []
    for name, address in addresses:
        key = address.casefold()
        if key not in seen:
            seen.add(key)
            result.append((name, address))
    return result


def _quoted_date(content):
    return content.date.astimezone().strftime("%d.%m.%Y o %H:%M") if content.date else ""


def _author(content):
    if content.from_addresses:
        name, address = content.from_addresses[0]
        return name or address
    return content.sender


def _quote(content):
    lead = _("W dniu {date}, {author} napisał(a):").format(
        date=_quoted_date(content), author=_author(content)
    )
    lines = "\n".join(f"> {line}" if line else ">" for line in content.body.split("\n"))
    return f"\n\n{lead}\n{lines}"


def reply_draft(content, own_email, reply_all=False):
    own = {own_email.casefold()}
    direct = content.reply_to_addresses or content.from_addresses
    if reply_all:
        to = _unique((*direct, *content.to_addresses), own) or list(direct)
        cc = _unique(content.cc_addresses, own | {a.casefold() for _n, a in to})
    else:
        to = list(direct)
        cc = []
    subject = content.subject
    if not REPLY_PREFIX_RE.match(subject):
        subject = f"Re: {subject}"
    return Draft(
        sender=own_email,
        to=_join(to),
        cc=_join(cc),
        subject=subject,
        body=_quote(content),
        in_reply_to=content.message_id,
        references=f"{content.references} {content.message_id}".strip(),
        focus_body=True,
    )


def forward_draft(content, own_email):
    subject = content.subject
    if not FORWARD_PREFIX_RE.match(subject):
        subject = f"Fwd: {subject}"
    header = "\n".join(
        (
            _("---------- Wiadomość przekazana ----------"),
            _("Od: {value}").format(value=content.sender),
            _("Data: {value}").format(value=_quoted_date(content)),
            _("Temat: {value}").format(value=content.subject),
            _("Do: {value}").format(value=content.recipients),
        )
    )
    return Draft(
        sender=own_email,
        subject=subject,
        body=f"\n\n{header}\n\n{content.body}",
        attachments=content.attachments,
    )


def _signature_block(signature):
    # Linia „-- ” to standardowy znak podpisu, po którym programy pocztowe go rozpoznają.
    return f"-- \n{signature}" if signature else ""


def add_signature(draft, signature):
    """Wstawia podpis nad cytatem, żeby stał tuż pod pisaną treścią."""
    if not signature:
        return draft
    return replace(draft, body=f"\n\n{_signature_block(signature)}{draft.body}")


def swap_signature(text, old, new, base):
    """Zmienia podpis po wyborze innego konta. base to treść pod podpisem, np. cytat."""
    old_block = _signature_block(old)
    new_block = _signature_block(new)
    if old_block and old_block in text:
        if new_block:
            return text.replace(old_block, new_block, 1)
        return text.replace(f"\n\n{old_block}", "", 1)
    if not new_block:
        return text
    if base and text.endswith(base):
        return f"{text[:-len(base)]}\n\n{new_block}{base}"
    return f"{text.rstrip()}\n\n{new_block}"


def parse_recipients(text):
    """Zwraca adresy z pola Do lub DW i listę fragmentów, które adresami nie są."""
    pairs = getaddresses([text.replace(";", ",")])
    valid = []
    invalid = []
    for name, address in pairs:
        if ADDRESS_RE.match(address) and address.isascii():
            valid.append(address)
        elif name or address:
            invalid.append(address or name)
    return valid, invalid


def attachment_from_file(path):
    path = Path(path)
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return Attachment(path.name, content_type, path.read_bytes())


def build_message(account, draft):
    message = EmailMessage()
    message["From"] = formataddr((account.display_name, account.email))
    if draft.to:
        message["To"] = draft.to.replace(";", ",")
    if draft.cc:
        message["Cc"] = draft.cc.replace(";", ",")
    message["Subject"] = draft.subject
    message["Date"] = formatdate(localtime=True)
    message["Message-ID"] = make_msgid(domain=account.email.rpartition("@")[2])
    if draft.in_reply_to:
        message["In-Reply-To"] = draft.in_reply_to
    if draft.references:
        message["References"] = draft.references
    message.set_content(draft.body)
    for attachment in draft.attachments:
        maintype, _slash, subtype = attachment.content_type.partition("/")
        message.add_attachment(
            attachment.data,
            maintype=maintype,
            subtype=subtype or "octet-stream",
            filename=attachment.filename,
        )
    return message.as_bytes(policy=SMTP)
