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

from enum import auto
from typing import TYPE_CHECKING, Generator

import numpy as np
from napari.components import ViewerModel as NapariViewerModel
from napari.layers import Image as NapariImage
from napari.utils.misc import StringEnum

from ._overlay import (
    ROIInteractionBoxHandle,
    ROIInteractionBoxOverlay,
    generate_roi_box_vertices,
    get_nearby_roi_handle,
)

if TYPE_CHECKING:
    from typing import Any

    import numpy.typing as npt
    from napari._vispy.mouse_event import NapariMouseEvent


class ROIMode(StringEnum):
    """Mode enum for ROI interaction."""

    NONE = auto()
    RESIZE = auto()


def generate_roi_box_from_layer(
    layer: NapariImage, dims_displayed: tuple[int, int]
) -> npt.NDArray[Any]:
    """
    Generate coordinates for the handles of a layer's transform box.

    Parameters
    ----------
    layer : Layer
        Layer whose transform box to generate.
    dims_displayed : Tuple[int, ...]
        Dimensions currently displayed (must be 2).

    Returns
    -------
    npt.NDArray[Any]
        Vertices and handles of the interaction box in data coordinates.
    """
    bounds = layer._display_bounding_box_augmented(list(dims_displayed))

    # generates in vispy canvas pos, so invert x and y, and then go back
    top_left, bot_right = (tuple(point) for point in bounds.T[:, ::-1])
    return generate_roi_box_vertices(top_left, bot_right)[:, ::-1]


def _adjust_roi_box(
    layer: DetectorLayer,
    nearby_handle: ROIInteractionBoxHandle,
    initial_handle_coords_data: npt.NDArray[Any],
    initial_world_to_data: npt.NDArray[Any],
    mouse_pos: npt.NDArray[Any],
) -> None: ...


def resize_roi_box(
    layer: DetectorLayer, event: NapariMouseEvent
) -> Generator[None, None, None]:
    """Resize the ROI box based on mouse movement.

    Parameters
    ----------
    layer : NapariImage
        The layer to resize the ROI box for.
    event : Event
        The event triggered by mouse movement.
    """
    if len(event.dims_displayed) != 2:
        return

    # we work in data space so we're axis aligned which simplifies calculation
    # same as Layer.data_to_world
    simplified = layer._transforms[1:].simplified
    initial_data_to_world = simplified.set_slice(layer._slice_input.displayed)
    initial_world_to_data = initial_data_to_world.inverse
    initial_mouse_pos = np.array(event.position)[event.dims_displayed]
    initial_mouse_pos_data = initial_world_to_data(initial_mouse_pos)

    initial_handle_coords_data = generate_roi_box_from_layer(
        layer, layer._slice_input.displayed
    )
    nearby_handle = get_nearby_roi_handle(
        initial_mouse_pos_data, initial_handle_coords_data
    )

    if nearby_handle is None:
        return

    # now that we have the nearby handles, other calculations need
    # the world space handle positions
    initial_data_to_world(initial_handle_coords_data)

    yield

    while event.type == "mouse_move":
        mouse_pos = np.array(event.position)[event.dims_displayed]
        _adjust_roi_box(
            layer,
            nearby_handle,
            initial_handle_coords_data,
            initial_world_to_data,
            mouse_pos,
        )


def highlight_roi_box_handles(layer: DetectorLayer, event: NapariMouseEvent) -> None:
    """Highlight the hovered handle of a ROI."""
    if len(event.dims_displayed) != 2:
        return

    # we work in data space so we're axis aligned which simplifies calculation
    # same as Layer.world_to_data
    world_to_data = (
        layer._transforms[1:].set_slice(layer._slice_input.displayed).inverse
    )
    pos = np.array(world_to_data(event.position))[event.dims_displayed]
    handle_coords = generate_roi_box_from_layer(layer, layer._slice_input.displayed)
    # TODO: dynamically set tolerance based on canvas size so it's not hard to pick small layer
    nearby_handle = get_nearby_roi_handle(pos, handle_coords)

    # set the selected vertex of the box to the nearby_handle (can also be INSIDE or None)
    layer.roi.selected_handle = nearby_handle


class DetectorLayer(NapariImage):
    """Layer for displaying data from a 2D detector (i.e. a camera)."""

    _move_modes = NapariImage._move_modes.update(
        {ROIMode.RESIZE: highlight_roi_box_handles}
    )

    _drag_modes = NapariImage._drag_modes.update(
        {
            # TODO: write a function to resize the ROI
            ROIMode.RESIZE: lambda x, y: (x, y),
        }
    )

    def _post_init(self) -> None:
        """Post-initialization of the layer.

        Adds a ROI box overlay to the layer.
        """
        overlay = ROIInteractionBoxOverlay(
            bounds=((0, 0), (self.data.shape[1], self.data.shape[0]))
        )
        self._overlays.update({"roi_box": overlay})

    @property
    def roi(self) -> ROIInteractionBoxOverlay:
        """Returns the ROI box overlay."""
        return self._overlays["roi_box"]

    @property
    def protected(self) -> bool:
        """Marks the layer as protected. Always returns True."""
        return True


class ViewerModel(NapariViewerModel):
    """Subclass of napari.components.ViewerModel to add custom functionality."""

    def add_detector(self, data: npt.NDArray[Any], **kwargs: Any) -> None:
        """Add a ``DetectorLayer`` to the viewer.

        Detector layers are intended to display data incoming from a 2D detector (i.e. a camera).

        Parameters
        ----------
        data : np.ndarray
            The data to be added as a detector.
        """
        layer = DetectorLayer(data, **kwargs)
        self.layers.append(layer)
