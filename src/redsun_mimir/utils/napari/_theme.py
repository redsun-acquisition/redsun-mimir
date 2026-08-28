from __future__ import annotations

from typing import cast

from napari._qt.qt_resources import get_stylesheet
from napari.settings import get_settings


def stylesheet() -> str:
    """Return napari's QSS for the theme and font size currently in settings."""
    settings = get_settings()
    return cast(
        "str",
        get_stylesheet(
            settings.appearance.theme,
            extra_variables={"font_size": f"{settings.appearance.font_size}pt"},
        ),
    )
