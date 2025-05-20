# parts of the source code are adapted from napari;
# the license is as follows:

# BSD 3-Clause License

# Copyright (c) 2018, Napari
# All rights reserved.

# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:

# * Redistributions of source code must retain the above copyright notice, this
#   list of conditions and the following disclaimer.

# * Redistributions in binary form must reproduce the above copyright notice,
#   this list of conditions and the following disclaimer in the documentation
#   and/or other materials provided with the distribution.

# * Neither the name of the copyright holder nor the names of its
#   contributors may be used to endorse or promote products derived from
#   this software without specific prior written permission.

# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
# FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
# SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
# OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
from __future__ import annotations

from typing import TYPE_CHECKING

from napari._vispy.overlays.base import LayerOverlayMixin, VispySceneOverlay
from napari._vispy.visuals.interaction_box import InteractionBox
from napari.components.overlays.base import SceneOverlay
from napari.components.overlays.interaction_box import (
    InteractionBoxHandle,  # noqa: TC002
)
from napari.layers.utils.interaction_box import (
    calculate_bounds_from_contained_points,
)

if TYPE_CHECKING:
    from typing import Any

    import numpy.typing as npt
    from napari.layers import Image
    from vispy.scene.node import Node


class ROIInteractionBoxOverlay(SceneOverlay):  # type: ignore[misc]
    """A box to select a region of interest in an image.

    Attributes
    ----------
    visible : bool
        If the overlay is visible or not.
    opacity : float
        The opacity of the overlay. 0 is fully transparent.
    bounds : tuple[Tuple[float, float], Tuple[float, float]]
        The bounds of the overlay, formatted as ((x0, y0), (x1, y1)).
        During initialization, they coincide with the bounds of the
        associated layer.
    selected_handle : Optional[ROIInteractionBoxHandle]
        The currently selected handle.
    """

    bounds: tuple[tuple[float, float], tuple[float, float]]
    selected_handle: InteractionBoxHandle | None = None

    def update_from_points(self, points: npt.NDArray[Any]) -> None:
        """Create as a bounding box of the given points."""
        self.bounds = calculate_bounds_from_contained_points(points)


class VispyROIBoxOverlay(LayerOverlayMixin, VispySceneOverlay):  # type: ignore[misc]
    """Vispy overlay, connected to an assigne Image layer and its associated ROIInteractionBoxOverlay.

    Provides a visual representation of the region of interest (ROI) in the image layer.

    Parameters
    ----------
    layer : Image
        The image layer to which the overlay is associated.
    overlay : ROIInteractionBoxOverlay
        The overlay that provides the bounds and selected handle for the ROI.
    parent : Node, optional
        The parent node in the Vispy scene graph. If not provided, defaults to None.
    """

    node: InteractionBox
    overlay: ROIInteractionBoxOverlay
    layer: Image

    def __init__(
        self,
        *,
        layer: Image,
        overlay: ROIInteractionBoxOverlay,
        parent: Node | None = None,
    ) -> None:
        super().__init__(
            node=InteractionBox(), layer=layer, overlay=overlay, parent=parent
        )
        self.layer.events.set_data.connect(self._on_visible_change)
        self.overlay.events.bounds.connect(self._on_bounds_change)
        self.overlay.events.selected_handle.connect(self._on_bounds_change)

    def _on_bounds_change(self) -> None:
        if self.layer._slice_input.ndisplay == 2:
            self.node.set_data(
                *self.overlay.bounds,
                selected=self.overlay.selected_handle,
                handles=True,
            )

    def _on_visible_change(self) -> None:
        if self.layer._slice_input.ndisplay == 2:
            super()._on_visible_change()
        else:
            self.node.visible = False

    def reset(self) -> None:
        super().reset()
        self._on_bounds_change()
