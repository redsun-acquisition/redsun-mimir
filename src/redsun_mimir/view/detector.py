from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING, Any

from bluesky.protocols import Descriptor, Reading  # noqa: TC002
from qtpy import QtWidgets
from redsun.log import Loggable
from redsun.utils.descriptors import parse_key
from redsun.view import ViewPosition
from redsun.view.qt import QtView
from redsun.view.qt.treeview import DescriptorTreeView
from redsun.virtual import Signal, slot

from redsun_mimir.providers import DETECTOR_DESCRIPTORS, DETECTOR_READINGS
from redsun_mimir.roi import Roi

if TYPE_CHECKING:
    from redsun.virtual import VirtualContainer


class RoiPanel(QtWidgets.QWidget):
    """The region a detector reads, and the one drawn on its image but not yet applied.

    Confirm applies the drawn region; Clear applies the whole sensor. Neither
    changes the camera by itself: both emit ``sig_roi_requested`` with the
    region, as ``"x,y,width,height"``.

    Parameters
    ----------
    sensor :
        The whole sensor, ``(width, height)``.
    applied :
        The region the camera reads now.
    """

    sig_roi_requested = Signal(str)

    def __init__(
        self,
        sensor: tuple[int, int],
        applied: Roi,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent=parent)
        self.sensor = sensor
        self.applied = applied
        self.pending: Roi | None = None

        self.label = QtWidgets.QLabel(self)
        self.confirm_button = QtWidgets.QPushButton("Confirm", self)
        self.confirm_button.setToolTip("Read out the region drawn on the image")
        self.confirm_button.setEnabled(False)
        self.clear_button = QtWidgets.QPushButton("Clear", self)
        self.clear_button.setToolTip("Read out the whole sensor")
        self.confirm_button.clicked.connect(self._on_confirm)
        self.clear_button.clicked.connect(self._on_clear)

        layout = QtWidgets.QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QtWidgets.QLabel("ROI", self))
        layout.addWidget(self.label, 1)
        layout.addWidget(self.confirm_button)
        layout.addWidget(self.clear_button)
        self.setLayout(layout)
        self._show()

    def draw(self, roi: Roi) -> None:
        """Show *roi* as the region drawn, awaiting confirmation."""
        self.pending = roi
        self.confirm_button.setEnabled(roi != self.applied)
        self._show()

    def apply(self, roi: Roi) -> None:
        """Show *roi* as the region the camera now reads."""
        self.applied = roi
        self.pending = None
        self.confirm_button.setEnabled(False)
        self._show()

    def _show(self) -> None:
        text = str(self.applied)
        if self.pending is not None and self.pending != self.applied:
            text = f"{text}  ->  {self.pending}"
        self.label.setText(text)

    def _on_confirm(self) -> None:
        if self.pending is not None:
            self.sig_roi_requested.emit(str(self.pending))

    def _on_clear(self) -> None:
        width, height = self.sensor
        self.sig_roi_requested.emit(str(Roi(0, 0, width, height)))


class SettingsControlWidget(QtWidgets.QWidget):
    """Widget for controlling device settings, backed by a descriptor tree view.

    Parameters
    ----------
    descriptors : dict[str, Descriptor]
        Detector output of "describe()".
    readings : dict[str, Reading[Any]]
        Detector output of "read()".
    parent : QtWidgets.QWidget | None, optional
        Optional parent widget.
    """

    def __init__(
        self,
        descriptors: dict[str, Descriptor],
        readings: dict[str, Reading[Any]],
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent=parent)

        self.tree_view = DescriptorTreeView(descriptors, readings, parent=self)
        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(self.tree_view)
        self.roi_panel = self._roi_panel(readings)
        if self.roi_panel is not None:
            layout.addWidget(self.roi_panel)
        self.setLayout(layout)

    def _roi_panel(self, readings: dict[str, Reading[Any]]) -> RoiPanel | None:
        """Build the ROI panel for a detector reporting a sensor size and a ROI."""
        sensor = next(
            (r for k, r in readings.items() if k.endswith("-sensor_size")), None
        )
        roi = next((r for k, r in readings.items() if k.endswith("-roi")), None)
        if sensor is None or roi is None:
            return None
        width, height = (int(item) for item in sensor["value"])
        return RoiPanel((width, height), Roi.parse(str(roi["value"])), self)


class DetectorView(QtView, Loggable):
    """View for interactive detector settings control.

    Renders per-detector property panels in a tabbed widget and forwards
    user edits to the
    [`DetectorPresenter`][redsun_mimir.presenter.DetectorPresenter]
    via the virtual bus.

    Image visualisation is handled independently by
    [`ImageView`][redsun_mimir.view.ImageView]; the two views share only
    the virtual bus and do not hold references to each other. The region
    drawn there reaches this view's ROI panel over the bus, and only Confirm
    or Clear sends a region to the camera, as a property change like any
    other.

    Parameters
    ----------
    name: str
        Identity key of the view.

    Attributes
    ----------
    sig_property_changed : Signal[str, str, Any]
        Emitted when the user changes a detector property.
        - str: The detector name.
        - str: The property name.
        - Any: The new value of the property.
    """

    sig_property_changed = Signal(str, str, object)

    @property
    def view_position(self) -> ViewPosition:
        """The position in the main view."""
        return ViewPosition.RIGHT

    def __init__(
        self,
        name: str,
        /,
    ) -> None:
        super().__init__(name)

        self.settings_tab_widget = QtWidgets.QTabWidget()
        self.settings_tab_widget.setMinimumWidth(300)

        layout = QtWidgets.QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.settings_tab_widget)
        self.setLayout(layout)

        self.settings_controls: dict[str, SettingsControlWidget] = {}

        self.logger.info("Initialized")

    def register_providers(self, container: VirtualContainer) -> None:
        """Register detector view signals in the virtual container."""
        container.register_signals(self)

    def inject_dependencies(self, container: VirtualContainer) -> None:
        """Build the settings panels from the detector presenter's snapshots."""
        self.setup_ui(
            container.require(DETECTOR_DESCRIPTORS),
            container.require(DETECTOR_READINGS),
        )

    def setup_ui(
        self,
        descriptors: dict[str, Descriptor],
        readings: dict[str, Reading[Any]],
    ) -> None:
        r"""Initialise the settings panels.

        Parameters
        ----------
        descriptors : dict[str, Descriptor]
            Flat merged ``describe()`` output from all detectors, keyed identically.
        readings : dict[str, Reading[Any]]
            Flat merged ``read()`` output from all detectors, keyed identically.
        """
        devices: dict[str, dict[str, Descriptor]] = {}
        for key, descriptor in descriptors.items():
            try:
                name, _ = parse_key(key)
            except ValueError:
                self.logger.warning(f"Skipping malformed descriptor key: {key!r}")
                continue
            devices.setdefault(name, {})[key] = descriptor

        for device_label, dev_descriptors in devices.items():
            dev_readings = {k: v for k, v in readings.items() if k in dev_descriptors}

            widget = SettingsControlWidget(dev_descriptors, dev_readings, self)
            widget.tree_view.sig_property_changed.connect(self.sig_property_changed)
            if widget.roi_panel is not None:
                widget.roi_panel.sig_roi_requested.connect(
                    partial(self.sig_property_changed.emit, device_label, "roi")
                )
            self.settings_controls[device_label] = widget
            self.settings_tab_widget.addTab(widget, device_label)

    @slot
    def on_roi_drawn(self, detector: str, roi: Roi) -> None:
        """Show the region drawn on *detector*'s image, for the user to confirm."""
        widget = self.settings_controls.get(detector)
        if widget is not None and widget.roi_panel is not None:
            widget.roi_panel.draw(roi)

    @slot
    def on_new_configuration(self, detector: str, key: str, value: Any) -> None:
        """Clear the pending edit for *key* once the presenter applied it.

        [`DetectorPresenter`][redsun_mimir.presenter.DetectorPresenter] only
        emits ``sig_new_configuration`` after a successful ``set``, so the
        edit is always confirmed here; failures are logged by the presenter
        and leave the pending value in place.

        Parameters
        ----------
        detector : str
            Name of the detector that applied the change.
        key : str
            Canonical ``name-property`` key of the setting that was applied.
        value : Any
            New value read back from the device.
        """
        widget = self.settings_controls.get(detector)
        if widget is None:
            self.logger.warning(f"No settings panel for detector {detector!r}")
            return
        widget.tree_view.confirm_change(key, True)
        if key == f"{detector}-roi" and widget.roi_panel is not None:
            widget.roi_panel.apply(Roi.parse(str(value)))
