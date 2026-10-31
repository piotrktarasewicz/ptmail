import email
from datetime import datetime, timezone
from email.policy import default

from ptmail.accounts import Account
from ptmail.compose import (
    Draft,
    add_signature,
    build_message,
    forward_draft,
    parse_recipients,
    reply_draft,
    swap_signature,
)
from ptmail.message_parser import parse_message
from ptmail.models import Attachment, MessageContent

ME = "ja@example.com"
ACCOUNT = Account("Praca", ME, "icloud")


def original(**changes):
    values = dict(
        sender="Jan Kowalski <jan@example.com>",
        recipients="Ja <JA@example.com>, Anna <anna@example.com>",
        subject="Faktura",
        date=datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc),
        body="Dzień dobry\n\nPozdrawiam",
        attachments=(),
        from_addresses=(("Jan Kowalski", "jan@example.com"),),
        to_addresses=(("Ja", "JA@example.com"), ("Anna", "anna@example.com")),
        cc_addresses=(("", "szef@example.com"), ("Ja", "ja@example.com")),
        message_id="<1@example.com>",
        references="<0@example.com>",
    )
    values.update(changes)
    return MessageContent(**values)


def parsed(raw):
    return email.message_from_bytes(raw, policy=default)


def test_reply_goes_to_sender_with_quote_and_threading():
    draft = reply_draft(original(), ME)
    assert draft.to == "Jan Kowalski <jan@example.com>"
    assert draft.cc == ""
    assert draft.subject == "Re: Faktura"
    assert draft.focus_body
    assert draft.body.startswith("\n\nW dniu ")
    assert "Jan Kowalski napisał(a):\n> Dzień dobry\n>\n> Pozdrawiam" in draft.body
    assert draft.in_reply_to == "<1@example.com>"
    assert draft.references == "<0@example.com> <1@example.com>"


def test_reply_prefers_reply_to_and_keeps_prefix():
    draft = reply_draft(
        original(subject="RE: Faktura", reply_to_addresses=(("", "biuro@example.com"),)),
        ME,
    )
    assert draft.to == "biuro@example.com"
    assert draft.subject == "RE: Faktura"


def test_reply_all_removes_own_address_and_duplicates():
    draft = reply_draft(
        original(cc_addresses=(("", "szef@example.com"), ("", "anna@example.com"))),
        ME,
        reply_all=True,
    )
    assert draft.to == "Jan Kowalski <jan@example.com>, Anna <anna@example.com>"
    assert draft.cc == "szef@example.com"


def test_reply_all_to_own_message_keeps_a_recipient():
    content = original(
        from_addresses=(("Ja", ME),), to_addresses=(), cc_addresses=()
    )
    assert reply_draft(content, ME, reply_all=True).to == f"Ja <{ME}>"


def test_name_with_comma_stays_one_recipient():
    content = original(from_addresses=(("Kowalski, Jan", "jan@example.com"),))
    draft = reply_draft(content, ME)
    assert parse_recipients(draft.to) == (["jan@example.com"], [])


def test_forward_keeps_attachments_and_leaves_recipient_empty():
    attachment = Attachment("a.pdf", "application/pdf", b"PDF")
    draft = forward_draft(original(attachments=(attachment,)), ME)
    assert draft.to == ""
    assert draft.subject == "Fwd: Faktura"
    assert draft.attachments == (attachment,)
    assert not draft.focus_body
    assert "Od: Jan Kowalski <jan@example.com>" in draft.body
    assert draft.body.endswith("Dzień dobry\n\nPozdrawiam")


def test_signature_on_new_message():
    assert add_signature(Draft(), "Jan\nFirma").body == "\n\n-- \nJan\nFirma"


def test_no_signature_leaves_draft_unchanged():
    draft = Draft(body="x")
    assert add_signature(draft, "") is draft


def test_signature_stands_above_quote():
    draft = add_signature(reply_draft(original(), ME), "Jan")
    assert draft.body.startswith("\n\n-- \nJan\n\nW dniu ")
    assert draft.body.endswith("> Pozdrawiam")


def test_swap_replaces_signature_and_keeps_typed_text():
    quote = "\n\nW dniu x:\n> y"
    text = f"Moja treść\n\n-- \nJan\n{quote}"
    assert (
        swap_signature(text, "Jan", "Firma", quote)
        == f"Moja treść\n\n-- \nFirma\n{quote}"
    )


def test_swap_to_account_with_signature_goes_above_quote():
    quote = "\n\nW dniu x:\n> y"
    assert (
        swap_signature(f"Treść{quote}", "", "Jan", quote)
        == f"Treść\n\n-- \nJan{quote}"
    )


def test_swap_on_new_message_appends():
    assert swap_signature("Treść\n", "", "Jan", "") == "Treść\n\n-- \nJan"


def test_swap_after_user_edited_signature_does_not_duplicate_old_text():
    assert swap_signature("Treść\n\n-- \nJan zmieniony", "Inny", "", "") == (
        "Treść\n\n-- \nJan zmieniony"
    )


def test_swap_to_no_signature_removes_block():
    assert swap_signature("Treść\n\n-- \nJan", "Jan", "", "") == "Treść"
    quote = "\n\nW dniu x:\n> y"
    assert swap_signature(f"\n\n-- \nJan{quote}", "Jan", "", quote) == quote


def test_signature_reaches_recipient():
    draft = add_signature(Draft(body=""), "Paweł Żółć")
    assert parse_message(build_message(ACCOUNT, draft)).body.endswith("Paweł Żółć")


def test_parse_recipients():
    assert parse_recipients("a@b.pl, Jan <c@d.pl>; e@f.pl") == (
        ["a@b.pl", "c@d.pl", "e@f.pl"],
        [],
    )
    assert parse_recipients("a@b.pl, jan") == (["a@b.pl"], ["jan"])
    assert parse_recipients("") == ([], [])


def test_build_message_round_trip():
    attachment = Attachment("faktura październik.pdf", "application/pdf", b"PDF")
    draft = Draft(
        to="Paweł Żółć <a@b.pl>; c@d.pl",
        cc="e@f.pl",
        subject="Zażółć gęślą jaźń",
        body="Treść z polskimi znakami\nDruga linia",
        attachments=(attachment,),
        in_reply_to="<1@b.pl>",
        references="<0@b.pl> <1@b.pl>",
    )
    raw = build_message(ACCOUNT, draft)
    assert raw.isascii() or b"\r\n" in raw
    message = parsed(raw)
    assert message["From"] == ME
    assert message["Subject"] == "Zażółć gęślą jaźń"
    assert [a.addr_spec for a in message["To"].addresses] == ["a@b.pl", "c@d.pl"]
    assert message["To"].addresses[0].display_name == "Paweł Żółć"
    assert message["In-Reply-To"] == "<1@b.pl>"
    assert message["Message-ID"].endswith("@example.com>")
    content = parse_message(raw)
    assert content.body == "Treść z polskimi znakami\nDruga linia"
    assert [a.filename for a in content.attachments] == ["faktura październik.pdf"]
    assert content.attachments[0].data == b"PDF"


def test_sender_name_reaches_recipient_with_polish_letters():
    account = Account("Praca", ME, "icloud", "Paweł Żółć")
    raw = build_message(account, Draft(body="x"))
    assert raw.isascii()
    [address] = parsed(raw)["From"].addresses
    assert address.display_name == "Paweł Żółć"
    assert address.addr_spec == ME


def test_sender_name_with_comma_stays_one_address():
    account = Account("Praca", ME, "icloud", "Kowalski, Jan")
    [address] = parsed(build_message(account, Draft(body="x")))["From"].addresses
    assert address.display_name == "Kowalski, Jan"
    assert address.addr_spec == ME


def test_build_message_for_draft_without_recipients():
    message = parsed(build_message(ACCOUNT, Draft(body="szkic")))
    assert message["To"] is None
    assert message.get_content().strip() == "szkic"


def test_parse_message_collects_reply_data():
    raw = (
        b"From: =?UTF-8?Q?Pawe=C5=82?= <a@b.pl>\r\n"
        b"To: x@y.pl, Ja <ja@y.pl>\r\n"
        b"Cc: z@y.pl\r\n"
        b"Reply-To: r@y.pl\r\n"
        b"Message-ID: <7@b.pl>\r\n"
        b"References: <5@b.pl>\r\n <6@b.pl>\r\n\r\ntresc"
    )
    content = parse_message(raw)
    assert content.from_addresses == (("Paweł", "a@b.pl"),)
    assert content.to_addresses == (("", "x@y.pl"), ("Ja", "ja@y.pl"))
    assert content.cc_addresses == (("", "z@y.pl"),)
    assert content.reply_to_addresses == (("", "r@y.pl"),)
    assert content.message_id == "<7@b.pl>"
    assert content.references == "<5@b.pl> <6@b.pl>"
