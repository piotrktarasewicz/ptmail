from ptmail.attachments import can_open, safe_filename, save_to_folder, unique_path
from ptmail.formatting import (
    attachment_sentence,
    format_size,
    message_document,
    utf16_ranges,
)
from ptmail.models import Attachment, Link, MessageContent


def attachment(name, data=b"x", content_type="application/pdf"):
    return Attachment(name, content_type, data)


def test_safe_filename_blocks_path_escape():
    assert safe_filename("..\\..\\Windows\\zlo.exe") == "_.._Windows_zlo.exe"
    assert safe_filename("../etc/passwd") == "_etc_passwd"
    assert safe_filename('a:b*c?.pdf') == "a_b_c_.pdf"
    assert safe_filename("...") == "zalacznik"


def test_unique_path_does_not_overwrite(tmp_path):
    (tmp_path / "a.pdf").write_bytes(b"x")
    assert unique_path(tmp_path, "a.pdf").name == "a (1).pdf"


def test_save_all_keeps_files_with_same_name(tmp_path):
    save_to_folder([attachment("a.pdf", b"1"), attachment("a.pdf", b"2")], tmp_path)
    assert (tmp_path / "a.pdf").read_bytes() == b"1"
    assert (tmp_path / "a (1).pdf").read_bytes() == b"2"


def test_executable_attachments_cannot_be_opened():
    assert can_open(attachment("faktura.pdf"))
    assert not can_open(attachment("faktura.pdf.exe"))
    assert not can_open(attachment("skrypt.JS"))
    assert not can_open(attachment("wirus.exe."))


def test_attachment_sentence():
    assert (
        attachment_sentence(attachment("faktura.pdf", b"x" * 120 * 1024))
        == "faktura.pdf, PDF, 120 KB"
    )
    assert (
        attachment_sentence(attachment("zdjecie", b"x", "image/jpeg"))
        == "zdjecie, JPEG, 1 B"
    )


def test_utf16_ranges_count_emoji_twice():
    text = "😀 a 😀 bb"
    links = [Link(2, 3, "https://a.pl", "a"), Link(6, 8, "https://b.pl", "bb")]
    assert [item[:2] for item in utf16_ranges(text, links)] == [(3, 4), (8, 10)]


def test_format_size_uses_decimal_comma():
    assert format_size(int(1.5 * 1024 * 1024)) == "1,5 MB"


def test_message_document_layout():
    content = MessageContent(
        "Jan <jan@a.pl>", "ja@a.pl", "Temat", None, "Treść", (attachment("a.pdf"),)
    )
    assert message_document(content) == "Treść\n\nZałączniki: 1"
    plain = MessageContent("a", "b", "c", None, "d", ())
    assert message_document(plain) == "d\n\nBrak załączników"
    empty = MessageContent("a", "b", "c", None, "", ())
    assert message_document(empty) == "Brak załączników"
