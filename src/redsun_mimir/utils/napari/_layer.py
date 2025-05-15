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

from copy import deepcopy
from typing import TYPE_CHECKING, Generator, NamedTuple

import numpy as np
from napari.layers import Image as ImageLayer
from napari.layers.utils.interaction_box import generate_interaction_box_vertices

from ._overlay import (
    ROIInteractionBoxHandle,
    ROIInteractionBoxOverlay,
    get_nearby_roi_handle,
)

if TYPE_CHECKING:
    from napari._vispy.mouse_event import NapariMouseEvent


class MousePosition(NamedTuple):
    """Mouse position in data coordinates.

    Parameters
    ----------
    y : int
        Y coordinate of the mouse position.
    x : int
        X coordinate of the mouse position.
    """

    y: int
    x: int

    def __repr__(self) -> str:
        """Return a string representation of the mouse position."""
        return f"(y={self.y}, x={self.x})"


def resize_roi_box(
    layer: DetectorLayer, event: NapariMouseEvent
) -> Generator[None, None, None]:
    """Resize the ROI box based on mouse movement.

    Parameters
    ----------
    layer : DetectorLayer
        The layer to resize the ROI box for.
    event : NapariMouseEvent
        The event triggered by mouse movement.

    Yields
    ------
    None
        This is a generator function that handles mouse dragging.
    """
    if len(event.dims_displayed) != 2:
        return

    # Get the selected handle
    selected_handle = layer.roi.selected_handle
    if selected_handle is None:
        return

    current_bounds = deepcopy(layer.roi.bounds)

    event.handled = True
    yield

    # Main event loop for handling drag events
    while event.type == "mouse_move":
        event.handled = True
        mouse_pos = MousePosition(
            *tuple(
                layer.world_to_data(event.position)[event.dims_displayed].astype(
                    np.uint32
                )
            )
        )

        match selected_handle:
            case ROIInteractionBoxHandle.CENTER_LEFT:
                if mouse_pos.x >= 0 and mouse_pos.x <= layer.width - 1:
                    current_bounds = (
                        (mouse_pos.x, layer.roi.bounds[0][1]),
                        layer.roi.bounds[1],
                    )
            case ROIInteractionBoxHandle.CENTER_RIGHT:
                if mouse_pos.x >= 1 and mouse_pos.x <= layer.width:
                    current_bounds = (
                        layer.roi.bounds[0],
                        (mouse_pos.x, layer.roi.bounds[1][1]),
                    )
            case ROIInteractionBoxHandle.TOP_LEFT:
                if (mouse_pos.y >= 0 and mouse_pos.y <= layer.height - 1) and (
                    mouse_pos.x >= 0 and mouse_pos.x <= layer.width - 1
                ):
                    print("top left not implemented", mouse_pos)
            case ROIInteractionBoxHandle.TOP_RIGHT:
                if (mouse_pos.y >= 0 and mouse_pos.y <= layer.height - 1) and (
                    mouse_pos.x >= 1 and mouse_pos.x <= layer.width
                ):
                    print("top right not implemented", mouse_pos)
            case ROIInteractionBoxHandle.TOP_CENTER:
                if mouse_pos.y >= 0 and mouse_pos.y <= layer.height - 1:
                    current_bounds = (
                        (layer.roi.bounds[0][0], mouse_pos.y),
                        layer.roi.bounds[1],
                    )
            case ROIInteractionBoxHandle.BOTTOM_CENTER:
                if mouse_pos.y >= 1 and mouse_pos.y <= layer.height:
                    current_bounds = (
                        (layer.roi.bounds[0][0], mouse_pos.y),
                        layer.roi.bounds[1],
                    )
            case ROIInteractionBoxHandle.BOTTOM_LEFT:
                if (mouse_pos.y >= 1 and mouse_pos.y <= layer.height) and (
                    mouse_pos.x >= 0 and mouse_pos.x <= layer.width - 1
                ):
                    print("bottom left not implemented", mouse_pos)
            case ROIInteractionBoxHandle.BOTTOM_RIGHT:
                if (mouse_pos.y >= 1 and mouse_pos.y <= layer.height) and (
                    mouse_pos.x >= 1 and mouse_pos.x <= layer.width
                ):
                    print("bottom right not implemented", mouse_pos)

        layer.roi.bounds = deepcopy(current_bounds)
        yield


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

    handle_coords = generate_interaction_box_vertices(*layer.roi.bounds, handles=True)[
        :, ::-1
    ]
    nearby_handle = get_nearby_roi_handle(pos, handle_coords)

    # set the selected vertex of the box to the nearby_handle (can also be INSIDE or None)
    layer.roi.selected_handle = nearby_handle


class DetectorLayer(ImageLayer):  # type: ignore[misc]
    """Layer for displaying data from a 2D detector (i.e. a camera)."""

    def _post_init(self) -> None:
        """Add a ROI box overlay to the layer after initialization."""
        overlay = ROIInteractionBoxOverlay(
            bounds=((0, 0), (self.data.shape[1], self.data.shape[0])),
        )
        self._overlays.update({"roi_box": overlay})
        self.mouse_move_callbacks.insert(0, highlight_roi_box_handles)
        self.mouse_drag_callbacks.insert(0, resize_roi_box)

    @property
    def roi(self) -> ROIInteractionBoxOverlay:
        """Returns the ROI box overlay."""
        return self._overlays["roi_box"]  # type: ignore[no-any-return]

    @property
    def width(self) -> int:
        """Returns the width of the layer."""
        return self.data.shape[0]  # type: ignore[no-any-return]

    @property
    def height(self) -> int:
        """Returns the height of the layer."""
        return self.data.shape[1]  # type: ignore[no-any-return]
