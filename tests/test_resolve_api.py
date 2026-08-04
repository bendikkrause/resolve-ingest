"""Detecting and clearing the state where Resolve's UI blocks scripting.

Tested against a stand-in Resolve object — no Resolve needed.
"""

from __future__ import annotations

import pytest

from resolve_ingest.resolve_api import ResolveBusy, ensure_ui_ready


class FakeResolve:
    """Stands in for the Resolve app object.

    ``page`` of None reproduces an open Project Manager window, where every
    ProjectManager call returns None.
    """

    def __init__(self, page: str | None, opens_to: str | None = "media"):
        self.page = page
        self.opens_to = opens_to
        self.opened: list[str] = []

    def GetCurrentPage(self):  # noqa: N802 - mirrors Resolve's API
        return self.page

    def OpenPage(self, name):  # noqa: N802
        self.opened.append(name)
        self.page = self.opens_to
        return self.page is not None


def test_no_action_when_resolve_is_already_usable():
    resolve = FakeResolve(page="edit")
    assert ensure_ui_ready(resolve) is False
    assert resolve.opened == []


def test_project_manager_window_is_dismissed():
    resolve = FakeResolve(page=None)
    assert ensure_ui_ready(resolve) is True
    assert resolve.opened == ["media"]
    assert resolve.GetCurrentPage() == "media"


def test_raises_when_the_block_will_not_clear():
    """A modal dialog blocks scripting the same way, and OpenPage cannot clear it."""
    resolve = FakeResolve(page=None, opens_to=None)
    with pytest.raises(ResolveBusy) as excinfo:
        ensure_ui_ready(resolve)
    message = str(excinfo.value)
    assert "project manager" in message.lower()
    assert "dialog" in message.lower()
    assert "nothing has been changed" in message.lower()


def test_is_idempotent():
    """Safe to call more than once per run — build() and the GUI both call it."""
    resolve = FakeResolve(page=None)
    assert ensure_ui_ready(resolve) is True
    assert ensure_ui_ready(resolve) is False
    assert resolve.opened == ["media"]


@pytest.mark.parametrize("page", ["media", "cut", "edit", "fusion", "color", "deliver"])
def test_any_open_page_counts_as_usable(page):
    resolve = FakeResolve(page=page)
    assert ensure_ui_ready(resolve) is False
