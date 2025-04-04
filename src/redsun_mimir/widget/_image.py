from __future__ import annotations

from typing import TYPE_CHECKING, cast

from ndv import ArrayViewer
from qtpy import QtWidgets as QtW
from sunflare.view.qt import BaseQtWidget

if TYPE_CHECKING:
    from typing import Any

    from sunflare.config import RedSunSessionInfo
    from sunflare.virtual import VirtualBus

    from ._config import ImageWidgetInfo


class ImageWidget(BaseQtWidget):
    """Image widget for displaying images.

    Parameters
    ----------
    config : ``RedSunSessionInfo``
        Configuration information for the session.
    virtual_bus : ``VirtualBus``
        Reference to the virtual bus.
    *args : ``Any``
        Additional positional arguments.
    **kwargs : ``Any``
        Additional keyword arguments.
    """

    def __init__(
        self,
        config: RedSunSessionInfo,
        virtual_bus: VirtualBus,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        super().__init__(config, virtual_bus, *args, **kwargs)

        self._info: ImageWidgetInfo = cast(
            "ImageWidgetInfo", config.widgets["ImageWidgetInfo"]
        )

        self._viewer = ArrayViewer()

        layout = QtW.QVBoxLayout(self)
        layout.addWidget(self._viewer.widget())

    def registration_phase(self) -> None:
        self.virtual_bus.register_signals(self)

    def connection_phase(self) -> None: ...
