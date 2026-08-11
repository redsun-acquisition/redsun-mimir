from __future__ import annotations

from typing import TYPE_CHECKING, Any

from qtpy import QtCore, QtWidgets
from redsun.log import Loggable
from redsun.utils.descriptors import parse_key
from redsun.view import ViewPosition
from redsun.view.qt import QtView
from redsun.virtual import Signal

from redsun_mimir.providers import STATED_CONFIGURATION, STATED_DESCRIPTION

if TYPE_CHECKING:
    from bluesky.protocols import Descriptor, Reading
    from redsun.virtual import VirtualContainer


class FilterWheelView(QtView, Loggable):
    """View for filter wheel position selection.

    Builds one drop-down per device from the ``choices`` its descriptor
    publishes, so no position index ever reaches the UI.

    Parameters
    ----------
    name: str
        Identity key of the view.

    Attributes
    ----------
    sig_state_request : Signal[str, str]
        Emitted when the user selects a new position. Carries the device
        label (``str``) and the selected position name (``str``).
    """

    sig_state_request = Signal(str, str)

    @property
    def view_position(self) -> ViewPosition:
        """The position in the main view."""
        return ViewPosition.RIGHT

    def __init__(self, name: str, /) -> None:
        super().__init__(name)

        self._combos: dict[str, QtWidgets.QComboBox] = {}
        self._layout = QtWidgets.QVBoxLayout()
        self.setLayout(self._layout)

        self.logger.info("Initialized")

    def register_providers(self, container: VirtualContainer) -> None:
        """Register filter wheel view signals in the virtual container."""
        container.register_signals(self)

    def inject_dependencies(self, container: VirtualContainer) -> None:
        """Build the selectors from the filter wheel presenter's snapshots."""
        self.setup_ui(
            container.require(STATED_DESCRIPTION),
            container.require(STATED_CONFIGURATION),
        )

    def setup_ui(
        self,
        descriptors: dict[str, Descriptor],
        readings: dict[str, Reading[Any]],
    ) -> None:
        """Initialise one selector group per stated device.

        Parameters
        ----------
        descriptors : dict[str, Descriptor]
            Flat merged ``describe_configuration()`` output from all devices.
        readings : dict[str, Reading[Any]]
            Flat merged ``read_configuration()`` output, keyed identically.
        """
        for key, descriptor in descriptors.items():
            choices = descriptor.get("choices")
            if not choices:
                continue
            try:
                name, _ = parse_key(key)
            except ValueError:
                self.logger.warning(f"Skipping malformed descriptor key: {key!r}")
                continue

            combo = QtWidgets.QComboBox()
            combo.addItems(list(choices))
            reading = readings.get(key)
            current = reading["value"] if reading is not None else None
            if isinstance(current, str):
                # the reading is authoritative but the wheel may report a
                # position the descriptor does not name; leave the box on its
                # first entry rather than inventing one
                index = combo.findText(current)
                if index >= 0:
                    combo.setCurrentIndex(index)
                else:
                    self.logger.warning(
                        f"{name!r} reports unknown position {current!r}"
                    )
            # connect after seeding, so restoring the current position does
            # not look like a user request and move the wheel back
            combo.currentTextChanged.connect(
                lambda state, device=name: self.sig_state_request.emit(device, state)
            )

            group = QtWidgets.QGroupBox(name)
            group.setAlignment(QtCore.Qt.AlignmentFlag.AlignHCenter)
            group_layout = QtWidgets.QVBoxLayout()
            group_layout.addWidget(combo)
            group.setLayout(group_layout)

            self._combos[name] = combo
            self._layout.addWidget(group)
