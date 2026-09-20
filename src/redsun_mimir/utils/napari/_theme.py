from __future__ import annotations

from typing import cast

from napari._qt.qt_resources import get_stylesheet
from napari.settings import get_settings


def stylesheet(font_size: int | None = None) -> str:
    """Return napari's QSS for the theme currently in its settings.

    Parameters
    ----------
    font_size :
        Point size the sheet asks for. ``None`` takes napari's own setting,
        which is what its viewer is drawn with; a session applying the sheet
        to the whole application may want the platform's size instead, since
        every widget of its own is styled by it too.
    """
    settings = get_settings()
    size = settings.appearance.font_size if font_size is None else font_size
    return cast(
        "str",
        get_stylesheet(
            settings.appearance.theme,
            extra_variables={"font_size": f"{size}pt"},
        ),
    )
