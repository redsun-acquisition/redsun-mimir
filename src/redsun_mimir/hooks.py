"""Container hooks a session installs to run redsun inside napari's application."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from napari._qt.qt_event_loop import get_qapp

from redsun_mimir.utils.napari import stylesheet

if TYPE_CHECKING:
    from qtpy.QtWidgets import QApplication

__all__ = ["NapariApplication"]


class NapariApplication:
    """Runs the session on napari's application, themed like napari.

    Serves two hook points. ``create_application`` hands the container the
    application napari itself would build, carrying its name, icon, identifier
    and high-DPI attributes; ``configure_application`` puts napari's stylesheet
    on that application, so a window embedding a napari viewer is styled
    throughout rather than only where the viewer sits.

    The stylesheet is read from napari's settings once, as the session starts.
    """

    def create_application(self, argv: list[str]) -> QApplication:
        """Return napari's application, creating it if it does not exist.

        *argv* is not forwarded: napari builds its own, so that the name shown
        in the macOS application menu is the one it expects.
        """
        # TODO: get_qapp correctly returns QApplication,
        # but napari is not fully typed yet and it has no
        # py.typed marker in it's shipped files (apparently...).
        # for now we cast it but in the future it should not be
        return cast("QApplication", get_qapp())

    def configure_application(self, app: QApplication) -> None:
        """Put napari's stylesheet on *app*."""
        app.setStyleSheet(stylesheet())
