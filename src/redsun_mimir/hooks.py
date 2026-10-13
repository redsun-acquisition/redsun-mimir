"""Container hooks a session installs to run redsun inside napari's application."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, cast

from napari._qt.qt_event_loop import get_qapp

if TYPE_CHECKING:
    from qtpy.QtWidgets import QApplication

__all__ = ["FONT_SIZE", "NapariApplication"]

#: Point size every widget of a session is drawn at. napari's own size is
#: larger than a platform gives a Qt application, and would show on every
#: widget beside the viewer.
FONT_SIZE: Final = 9


class NapariApplication:
    """Hook running the session on napari's application.

    ``create_application`` hands the container the application napari itself
    would build, with its name, icon, identifier and high-DPI attributes.
    """

    def create_application(self, argv: list[str]) -> QApplication:
        """Return napari's application, creating it if it does not exist.

        *argv* is not forwarded: napari builds its own, so the macOS
        application menu shows the name it expects.
        """
        # TODO: get_qapp correctly returns QApplication,
        # but napari is not fully typed yet and it has no
        # py.typed marker in it's shipped files (apparently...).
        # for now we cast it but in the future it should not be
        return cast("QApplication", get_qapp())
