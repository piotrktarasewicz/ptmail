from email.message import EmailMessage

from ptmail.message_parser import html_to_text, linkify_text, parse_message


def base_message():
    message = EmailMessage()
    message["From"] = "Jan Kowalski <jan@example.com>"
    message["To"] = "piotr@example.com"
    message["Subject"] = "Faktura za październik"
    message["Date"] = "Fri, 30 Oct 2026 13:20:00 +0100"
    return message


def test_plain_text_headers_and_body():
    message = base_message()
    message.set_content("Dzień dobry\nW załączeniu faktura")
    content = parse_message(message.as_bytes())
    assert content.sender == "Jan Kowalski <jan@example.com>"
    assert content.recipients == "piotr@example.com"
    assert content.subject == "Faktura za październik"
    assert content.body == "Dzień dobry\nW załączeniu faktura"
    assert content.attachments == ()


def test_html_wins_over_plain_text():
    message = base_message()
    message.set_content("tekst")
    message.add_alternative("<p>html</p>", subtype="html")
    assert parse_message(message.as_bytes()).body == "html"


def test_plain_text_used_when_html_is_empty():
    message = base_message()
    message.set_content("tekst")
    message.add_alternative("<img src='a.png'>", subtype="html")
    assert parse_message(message.as_bytes()).body == "tekst"


def test_link_keeps_description_and_hides_address():
    message = base_message()
    message.set_content("<p>Cześć</p><p>Kliknij <a href='https://a.pl/x'>tutaj</a></p>", subtype="html")
    content = parse_message(message.as_bytes())
    assert content.body == "Cześć\n\nKliknij tutaj"
    [link] = content.links
    assert link.url == "https://a.pl/x"
    assert link.text == "tutaj"
    assert content.body[link.start:link.end] == "tutaj"


def test_long_tracking_address_becomes_short_label():
    url = "https://click.allegro.pl/ls/abc123def456ghi789jkl012mno345pqr678"
    text, links = html_to_text(f"<p>Płatność</p><a href='{url}'>{url}</a><p>Dziękujemy</p>")
    assert text == "Płatność\nlink click.allegro.pl\nDziękujemy"
    assert links[0].url == url


def test_plain_text_addresses_become_labels():
    text, links = linkify_text(
        "Zobacz https://www.a.pl/abc?x=1, oraz <https://b.pl/y>."
    )
    assert text == "Zobacz link a.pl, oraz link b.pl."
    assert [link.url for link in links] == ["https://www.a.pl/abc?x=1", "https://b.pl/y"]
    assert [text[link.start:link.end] for link in links] == ["link a.pl", "link b.pl"]


def test_images_are_skipped_unless_they_are_described_links():
    text, links = html_to_text(
        "<img src='a.png' alt='logo'>Treść"
        "<a href='https://a.pl/1'><img src='b.png'></a>"
        "<p><a href='https://a.pl/2'><img src='c.png' alt='Zapłać'></a></p>"
    )
    assert text == "Treść\nZapłać"
    assert [link.url for link in links] == ["https://a.pl/2"]


def test_link_spanning_blocks_stays_on_one_line():
    text, links = html_to_text("<a href='https://a.pl'><div>Zobacz</div><div>teraz</div></a>")
    assert text == "Zobacz teraz"
    assert links[0].text == "Zobacz teraz"


def test_unsafe_schemes_are_not_links():
    text, links = html_to_text("<a href='javascript:alert(1)'>kliknij</a><a href='file:///c:/x'>plik</a>")
    assert text == "kliknijplik"
    assert links == ()


def test_private_markers_in_mail_do_not_break_links():
    text, links = html_to_text("a\ue000b &#xe001;<a href='https://a.pl'>c</a>")
    assert text == "ab c"
    assert [(link.url, link.text) for link in links] == [("https://a.pl", "c")]


def test_attachment_with_polish_name_and_size():
    message = base_message()
    message.set_content("treść")
    message.add_attachment(
        b"%PDF", maintype="application", subtype="pdf", filename="faktura październik.pdf"
    )
    [attachment] = parse_message(message.as_bytes()).attachments
    assert attachment.filename == "faktura październik.pdf"
    assert attachment.content_type == "application/pdf"
    assert attachment.data == b"%PDF"


def test_attachment_nested_in_alternative_like_apple_mail():
    raw = (
        b"From: a@example.com\r\n"
        b"MIME-Version: 1.0\r\n"
        b'Content-Type: multipart/alternative; boundary="A"\r\n\r\n'
        b"--A\r\nContent-Type: text/plain\r\n\r\ntekst\r\n"
        b'--A\r\nContent-Type: multipart/mixed; boundary="B"\r\n\r\n'
        b"--B\r\nContent-Type: text/html\r\n\r\n<p>tekst</p>\r\n"
        b"--B\r\nContent-Type: application/pdf\r\n"
        b'Content-Disposition: attachment; filename="a.pdf"\r\n\r\nPDF\r\n'
        b"--B--\r\n--A--\r\n"
    )
    content = parse_message(raw)
    assert content.body == "tekst"
    assert [a.filename for a in content.attachments] == ["a.pdf"]
    assert content.links == ()


def test_inline_image_is_not_an_attachment():
    message = base_message()
    message.set_content("tekst")
    message.add_alternative("<img src='cid:logo'>", subtype="html")
    message.get_payload()[1].add_related(
        b"PNG",
        maintype="image",
        subtype="png",
        cid="<logo>",
        filename="logo.png",
        disposition="inline",
    )
    assert parse_message(message.as_bytes()).attachments == ()


def test_unknown_charset_does_not_crash():
    raw = (
        b"From: a@example.com\r\n"
        b"Content-Type: text/plain; charset=nieznany\r\n\r\ntekst"
    )
    assert parse_message(raw).body == "tekst"


def test_html_skips_styles_and_keeps_bare_address():
    html = (
        "<html><head><title>t</title><style>p {color: red}</style></head>"
        "<body>A&nbsp;B<br>"
        "<a href='https://a.pl'>https://a.pl</a> "
        "<a href='mailto:x@a.pl'>x@a.pl</a> "
        "<a href='#'>kotwica</a></body></html>"
    )
    text, links = html_to_text(html)
    assert text == "A B\nlink a.pl x@a.pl kotwica"
    assert [link.url for link in links] == ["https://a.pl", "mailto:x@a.pl"]
