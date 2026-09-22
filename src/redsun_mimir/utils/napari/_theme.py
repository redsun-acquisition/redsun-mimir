from __future__ import annotations

from typing import cast

from napari._qt.qt_resources import get_stylesheet
from napari.settings import get_settings


def stylesheet(font_size: int | None = None) -> str:
    """Return napari's QSS for the theme in its settings.

    *font_size* is in points; ``None`` takes napari's own setting, which its
    viewer is drawn with. A session styling the whole application may want
    the platform's size instead, since every widget of its own is styled too.
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
