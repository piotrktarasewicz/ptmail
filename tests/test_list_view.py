"""Lista wiadomości zmienia tylko to, co się zmieniło, żeby NVDA nie czytał wiersza od nowa."""

import pytest
import wx

from ptmail.ui.list_view import ROW_FOCUS_DELAY_MS, ListView, _changed_range


@pytest.fixture(scope="module")
def app():
    application = wx.App()
    yield application
    del application


@pytest.fixture
def view(app):
    frame = wx.Frame(None)
    window = ListView(frame, "Wiadomości")
    window.selections = []
    for name in ("Select", "Focus", "DeleteAllItems"):
        original = getattr(window.list, name)
        setattr(
            window.list,
            name,
            lambda *args, name=name, original=original: (
                window.selections.append((name, args)),
                original(*args),
            ),
        )
    yield window
    frame.Destroy()


def rows(*keys):
    return [(key, f"wiersz {key}") for key in keys]


def shown(view):
    return [view.list.GetItemText(i) for i in range(view.list.GetItemCount())]


def test_same_rows_change_nothing(view):
    view.set_rows(rows(3, 2, 1))
    view.select_key(2)
    view.selections.clear()
    view.set_rows(rows(3, 2, 1))
    view.select_key(2)
    assert view.selections == []


def test_new_row_on_top_keeps_selection_without_reselecting(view):
    view.set_rows(rows(2, 1))
    view.select_key(2)
    view.selections.clear()
    view.set_rows(rows(3, 2, 1))
    assert shown(view) == ["wiersz 3", "wiersz 2", "wiersz 1"]
    assert view.selected_key() == 2
    assert view.selections == []


def test_removed_row_elsewhere_keeps_selection(view):
    view.set_rows(rows(3, 2, 1))
    view.select_key(1)
    view.selections.clear()
    view.set_rows(rows(3, 1))
    assert view.selected_key() == 1
    assert view.selections == []


def test_removed_selected_row_moves_to_fallback(view):
    view.set_rows(rows(3, 2, 1))
    view.select_key(2)
    view.set_rows(rows(3, 1), fallback=1)
    assert view.selected_key() == 1


def test_changed_text_changes_only_that_row(view):
    view.set_rows(rows(2, 1))
    view.select_key(2)
    view.selections.clear()
    view.set_rows([(2, "wiersz 2"), (1, "nieprzeczytana, wiersz 1")])
    assert shown(view) == ["wiersz 2", "nieprzeczytana, wiersz 1"]
    assert view.selections == []


def test_empty_list_gets_fallback_selection(view):
    view.set_rows(rows(3, 2, 1), fallback=3)
    assert view.selected_key() == 3


def test_reversed_order_keeps_selected_message(view):
    view.set_rows(rows(3, 2, 1))
    view.select_key(2)
    view.set_rows(rows(1, 2, 3))
    assert shown(view) == ["wiersz 1", "wiersz 2", "wiersz 3"]
    assert view.selected_key() == 2


def test_changed_range():
    assert _changed_range([2, 1], [3, 2, 1]) == (0, 0, 1)
    assert _changed_range([3, 2, 1], [3, 1]) == (1, 2, 1)
    assert _changed_range([1, 2], [1, 2]) == (2, 2, 2)


def test_entering_list_focuses_row_a_moment_later(view, monkeypatch):
    later = []
    monkeypatch.setattr(
        "ptmail.ui.list_view.wx.CallLater", lambda ms, run, *args: later.append((ms, run))
    )
    view.set_rows(rows(3, 2, 1))
    view.select_key(2)
    view.focus()
    # Najpierw sama lista, bez wiersza z fokusem; NVDA nie dostaje dwóch zgłoszeń naraz.
    assert view.list.GetFocusedItem() == -1
    assert later == [(ROW_FOCUS_DELAY_MS, view._focus_selected_row)]
    view._focus_selected_row()
    assert view.list.GetFocusedItem() == 1
    assert view.selected_key() == 2


def test_new_rows_on_focused_list_focus_the_row_once_a_moment_later(view, monkeypatch):
    later = []
    monkeypatch.setattr(
        "ptmail.ui.list_view.wx.CallLater", lambda ms, run, *args: later.append((ms, run))
    )
    view.set_rows(rows(2, 1))
    view.select_key(2)
    monkeypatch.setattr(view, "_has_focus", lambda: True)
    view.set_rows(rows(3, 2, 1))
    view.select_key(3)
    # Nowy wiersz i zaznaczenie bez fokusu wiersza, który dochodzi raz, po chwili.
    assert view.selected_key() == 3
    assert view.list.GetFocusedItem() == -1
    assert later == [(ROW_FOCUS_DELAY_MS, view._focus_selected_row)]
    view._focus_selected_row()
    assert view.list.GetFocusedItem() == 0


def test_text_change_on_focused_list_keeps_row_focus(view, monkeypatch):
    later = []
    monkeypatch.setattr(
        "ptmail.ui.list_view.wx.CallLater", lambda ms, run, *args: later.append(run)
    )
    view.set_rows(rows(2, 1))
    view.select_key(2)
    monkeypatch.setattr(view, "_has_focus", lambda: True)
    view.set_rows([(2, "nowy tekst"), (1, "wiersz 1")])
    assert later == []
    assert view.list.GetFocusedItem() == 0


def test_held_row_focus_waits_for_its_own_delay(view, monkeypatch):
    later = []
    monkeypatch.setattr(
        "ptmail.ui.list_view.wx.CallLater", lambda ms, run, *args: later.append((ms, run))
    )
    view.hold_row_focus(1000)
    monkeypatch.setattr(view, "_has_focus", lambda: True)
    view.set_rows(rows(3, 2, 1), fallback=3)
    view.select_key(3)
    # Start: wiersze i zaznaczenie są od razu, fokus wiersza dopiero po sekundzie.
    assert view.selected_key() == 3
    assert view.list.GetFocusedItem() == -1
    assert later == [(1000, view._focus_selected_row)]
    view._focus_selected_row()
    assert view.list.GetFocusedItem() == 0
