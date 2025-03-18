from __future__ import annotations

from typing import TYPE_CHECKING

from pyqtgraph.parametertree import Parameter, ParameterTree
from qtpy import QtWidgets
from sunflare.view.qt import BaseQtWidget
from sunflare.virtual import Signal

from redsun_mimir.model import DetectorModelInfo

if TYPE_CHECKING:
    from typing import Any

    from bluesky.protocols import Descriptor, Reading
    from sunflare.config import RedSunSessionInfo
    from sunflare.virtual import VirtualBus

DESCRIPTOR_MAP = {
    "string": "str",
    "number": "float",
    "array": "list",
    "boolean": "bool",
    "integer": "int",
}


class DetectorWidget(BaseQtWidget):
    sigConfigRequest = Signal()

    def __init__(
        self,
        config: RedSunSessionInfo,
        virtual_bus: VirtualBus,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        super().__init__(config, virtual_bus, *args, **kwargs)
        self.detectors_info = {
            name: model_info
            for name, model_info in self.config.models.items()
            if isinstance(model_info, DetectorModelInfo)
        }
        self.parameter = Parameter.create(name="Detectors", type="group", children=[])
        self.tree = ParameterTree()
        self.tree.setParameters(self.parameter, showTop=False)
        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(self.tree)
        self.setLayout(layout)

    def registration_phase(self) -> None:
        self.virtual_bus.register_signals(self)

    def connection_phase(self) -> None:
        self.virtual_bus["DetectorController"]["sigDetectorConfigDescriptor"].connect(
            self._update_parameter_layout
        )
        self.virtual_bus["DetectorController"]["sigDetectorConfigReading"].connect(
            self._update_parameter
        )

    def _update_parameter_layout(
        self, detector: str, descriptor: dict[str, Descriptor]
    ) -> None:
        if any(child.name() == detector for child in self.parameter.children()):
            return
        params: dict[str, list[Parameter]] = {}
        for key, descriptor in descriptor.items():
            params.update({descriptor["source"]: []})
            dtype = descriptor["dtype"]
            new_param: dict[str, Any] = {
                "readonly": True if descriptor["source"] == "model_info" else False,
            }
            if dtype == "string" and len(descriptor["shape"]) > 0:
                # multi-choice enumerator
                new_param.update(
                    {
                        "name": key,
                        "type": "list",
                        "values": descriptor["choices"],
                        "value": descriptor["choices"][0],
                    }
                )
            else:
                new_param.update(
                    {
                        "name": key,
                        "type": DESCRIPTOR_MAP[dtype],
                        "value": None,
                    }
                )
            params[descriptor["source"]].append(Parameter.create(**new_param))
        for source, child in params.items():
            self.tree.addParameters(
                param=child,
                root=source,
            )

    def _update_parameter(
        self, detector: str, reading: dict[str, Reading[Any]]
    ) -> None: ...
