"""Nazwa programu w powiadomieniach Windows."""

from ptmail import notifications


class FakeKey:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def fake_shell(monkeypatch):
    ids = []
    shell32 = type(
        "Shell32",
        (),
        {"SetCurrentProcessExplicitAppUserModelID": staticmethod(ids.append)},
    )
    windll = type("Windll", (), {"shell32": shell32})
    monkeypatch.setattr(notifications.ctypes, "windll", windll)
    return ids


def test_program_introduces_itself_under_its_own_name(monkeypatch):
    ids = fake_shell(monkeypatch)
    keys = []
    values = []
    monkeypatch.setattr(
        notifications.winreg,
        "CreateKey",
        lambda root, path: keys.append((root, path)) or FakeKey(),
    )
    monkeypatch.setattr(
        notifications.winreg,
        "SetValueEx",
        lambda key, name, reserved, kind, value: values.append((name, value)),
    )
    notifications.register_app()
    assert keys == [
        (notifications.winreg.HKEY_CURRENT_USER, r"Software\Classes\AppUserModelId\PTMail")
    ]
    assert values == [("DisplayName", "PT Mail")]
    assert ids == ["PTMail"]


def test_registry_failure_does_not_stop_the_program(monkeypatch):
    ids = fake_shell(monkeypatch)

    def refuse(root, path):
        raise OSError("brak dostępu")

    monkeypatch.setattr(notifications.winreg, "CreateKey", refuse)
    notifications.register_app()
    assert ids == []
