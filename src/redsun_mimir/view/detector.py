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

from redsun_mimir.common import Roi
from redsun_mimir.providers import DETECTOR_DESCRIPTORS, DETECTOR_READINGS

if TYPE_CHECKING:
    from redsun.virtual import VirtualContainer


class RoiPanel(QtWidgets.QWidget):
    """The region a detector reads, and an editor for the next one.

    Select ROI opens the editor and shows the box on the image, announced on
    ``sig_selection_toggled``. The editor's spin boxes and the box show one
    region: dragging the box fills the spin boxes through `draw`, editing a
    spin box announces the region on ``sig_roi_edited``. Full fills in the
    whole sensor. OK emits ``sig_roi_requested`` with the region as
    ``"x,y,width,height"`` and closes the editor; nothing reaches the camera
    before that.

    Parameters
    ----------
    sensor :
        The whole sensor, ``(width, height)``.
    applied :
        The region the camera reads now.
    """

    sig_roi_requested = Signal(str)
    sig_roi_edited = Signal(object)
    sig_selection_toggled = Signal(bool)

    def __init__(
        self,
        sensor: tuple[int, int],
        applied: Roi,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent=parent)
        self.sensor = sensor
        self.applied = applied
        width, height = sensor

        self.label = QtWidgets.QLabel(self)
        self.select_button = QtWidgets.QPushButton("Select ROI", self)
        self.select_button.setToolTip("Show a box on the image to drag over the region")
        self.select_button.setCheckable(True)
        self.select_button.toggled.connect(self._on_select)

        self.editor = QtWidgets.QWidget(self)
        self.editor.setVisible(False)
        self.x_box = QtWidgets.QSpinBox(self.editor)
        self.x_box.setRange(0, width - 1)
        self.y_box = QtWidgets.QSpinBox(self.editor)
        self.y_box.setRange(0, height - 1)
        self.width_box = QtWidgets.QSpinBox(self.editor)
        self.width_box.setRange(1, width)
        self.height_box = QtWidgets.QSpinBox(self.editor)
        self.height_box.setRange(1, height)
        for box in self._boxes:
            box.valueChanged.connect(self._on_edit)
        self.full_button = QtWidgets.QPushButton("Full", self.editor)
        self.full_button.setToolTip("Fill in the whole sensor")
        self.full_button.clicked.connect(self._on_full)
        self.ok_button = QtWidgets.QPushButton("OK", self.editor)
        self.ok_button.setToolTip("Read out this region")
        self.ok_button.clicked.connect(self._on_ok)

        grid = QtWidgets.QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        for row, pairs in enumerate(
            (
                (("x", self.x_box), ("y", self.y_box)),
                (("width", self.width_box), ("height", self.height_box)),
            )
        ):
            for column, (name, box) in enumerate(pairs):
                grid.addWidget(QtWidgets.QLabel(name, self.editor), row, 2 * column)
                grid.addWidget(box, row, 2 * column + 1)
        buttons = QtWidgets.QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.full_button)
        buttons.addWidget(self.ok_button)
        grid.addLayout(buttons, 2, 0, 1, 4)
        self.editor.setLayout(grid)

        header = QtWidgets.QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.addWidget(QtWidgets.QLabel("ROI", self))
        header.addWidget(self.label, 1)
        header.addWidget(self.select_button)
        layout = QtWidgets.QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(header)
        layout.addWidget(self.editor)
        self.setLayout(layout)
        self._load(applied)
        self._show()

    @property
    def pending(self) -> Roi:
        """The region the editor shows."""
        return Roi(
            self.x_box.value(),
            self.y_box.value(),
            self.width_box.value(),
            self.height_box.value(),
        )

    def draw(self, roi: Roi) -> None:
        """Fill the editor with *roi*, the region dragged on the image."""
        self._load(roi)
        self._show()

    def apply(self, roi: Roi) -> None:
        """Show *roi* as the region the camera now reads."""
        self.applied = roi
        if not self.editor.isVisible():
            self._load(roi)
        self._show()

    @property
    def _boxes(self) -> tuple[QtWidgets.QSpinBox, ...]:
        return (self.x_box, self.y_box, self.width_box, self.height_box)

    def _load(self, roi: Roi) -> None:
        """Put *roi* in the spin boxes without announcing an edit."""
        for box in self._boxes:
            box.blockSignals(True)
        try:
            self.x_box.setValue(roi.x)
            self.y_box.setValue(roi.y)
            self._fit()
            self.width_box.setValue(roi.width)
            self.height_box.setValue(roi.height)
        finally:
            for box in self._boxes:
                box.blockSignals(False)

    def _fit(self) -> None:
        """Keep width and height inside the sensor from the corner chosen."""
        sensor_width, sensor_height = self.sensor
        self.width_box.setMaximum(sensor_width - self.x_box.value())
        self.height_box.setMaximum(sensor_height - self.y_box.value())

    def _show(self) -> None:
        self.label.setText(str(self.applied))
        self.ok_button.setEnabled(self.pending != self.applied)

    def _on_select(self, checked: bool) -> None:
        if checked:
            self._load(self.applied)
        self.editor.setVisible(checked)
        self._show()
        self.sig_selection_toggled.emit(checked)

    def _on_edit(self) -> None:
        for box in self._boxes:
            box.blockSignals(True)
        try:
            self._fit()
        finally:
            for box in self._boxes:
                box.blockSignals(False)
        self._show()
        self.sig_roi_edited.emit(self.pending)

    def _on_full(self) -> None:
        width, height = self.sensor
        self._load(Roi(0, 0, width, height))
        self._show()
        self.sig_roi_edited.emit(self.pending)

    def _on_ok(self) -> None:
        self.sig_roi_requested.emit(str(self.pending))
        self.select_button.setChecked(False)


class SettingsControlWidget(QtWidgets.QWidget):
    """Widget for a detector's settings, backed by a descriptor tree view.

    *descriptors* and *readings* are the detector's ``describe()`` and
    ``read()`` output.
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

    One property panel per detector in a tabbed widget; edits go to
    [`DetectorPresenter`][redsun_mimir.presenter.DetectorPresenter] over the
    virtual bus. Images are shown by [`ImageView`][redsun_mimir.view.ImageView],
    which shares only the bus with this view: the region drawn there reaches
    the ROI panel over it, an edit in the panel reaches the box the same
    way, and only OK sends a region to the camera, as a property change
    like any other.

    Attributes
    ----------
    sig_property_changed : Signal[str, str, Any]
        Emitted when the user changes a detector property, with the detector
        name, the property name and the new value.
    sig_roi_selection : Signal[str, bool]
        Emitted when the user asks to select a region on a detector's image,
        or stops: the detector name, and whether the box is wanted.
    sig_roi_edited : Signal[str, Roi]
        Emitted when the user edits the region in a detector's panel, for
        the box on its image to follow.
    """

    sig_property_changed = Signal(str, str, object)
    sig_roi_selection = Signal(str, bool)
    sig_roi_edited = Signal(str, object)

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
        """Register the view's signals with the container."""
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
        r"""Build one settings panel per detector.

        *descriptors* and *readings* are the ``describe()`` and ``read()``
        output of every detector, merged flat.
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
                widget.roi_panel.sig_selection_toggled.connect(
                    partial(self.sig_roi_selection.emit, device_label)
                )
                widget.roi_panel.sig_roi_edited.connect(
                    partial(self.sig_roi_edited.emit, device_label)
                )
            self.settings_controls[device_label] = widget
            self.settings_tab_widget.addTab(widget, device_label)

    @slot
    def on_roi_drawn(self, detector: str, roi: Roi) -> None:
        """Fill *detector*'s editor with the region dragged on its image."""
        widget = self.settings_controls.get(detector)
        if widget is not None and widget.roi_panel is not None:
            widget.roi_panel.draw(roi)

    @slot
    def on_new_configuration(self, detector: str, key: str, value: Any) -> None:
        """Clear the pending edit for *key* once the presenter applied it.

        Reached only after a successful ``set``: a failure is logged by the
        presenter and leaves the pending value in place. *key* is the
        ``name-property`` key of the setting, *value* what the device reads
        back.
        """
        widget = self.settings_controls.get(detector)
        if widget is None:
            self.logger.warning(f"No settings panel for detector {detector!r}")
            return
        widget.tree_view.confirm_change(key, True)
        if key == f"{detector}-roi" and widget.roi_panel is not None:
            widget.roi_panel.apply(Roi.parse(str(value)))
