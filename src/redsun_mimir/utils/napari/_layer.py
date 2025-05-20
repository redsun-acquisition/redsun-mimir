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
from napari.components.overlays.interaction_box import InteractionBoxHandle
from napari.layers.utils.interaction_box import (
    generate_interaction_box_vertices,
    get_nearby_handle,
)

if TYPE_CHECKING:
    from napari._vispy.mouse_event import NapariMouseEvent
    from napari.layers import Image


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
    layer: Image, event: NapariMouseEvent
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
    selected_handle = layer._overlays["roi_box"].selected_handle
    if selected_handle is None or selected_handle in [
        InteractionBoxHandle.INSIDE,
        InteractionBoxHandle.ROTATION,
    ]:
        # If no handle is selected or the selected handle is INSIDE or ROTATION, do nothing
        return

    current_bounds = deepcopy(layer._overlays["roi_box"].bounds)

    width, height = layer.data.shape[0], layer.data.shape[1]
    # this event.handled assignment should not be necessary;
    # it is kept to show the problem
    event.handled = True
    yield

    # Main event loop for handling drag events
    while event.type == "mouse_move":
        # this event.handled assignment should prevent propagation
        # to the pan-zoom event handler, but it does not and the
        # pan-zoom event handler is called anyway
        event.handled = True
        mouse_pos = MousePosition(
            *tuple(
                layer.world_to_data(event.position)[event.dims_displayed].astype(
                    np.uint32
                )
            )
        )

        match selected_handle:
            case InteractionBoxHandle.CENTER_LEFT:
                if mouse_pos.x >= 0 and mouse_pos.x <= width - 1:
                    current_bounds = (
                        (mouse_pos.x, layer._overlays["roi_box"].bounds[0][1]),
                        layer._overlays["roi_box"].bounds[1],
                    )
            case InteractionBoxHandle.CENTER_RIGHT:
                if mouse_pos.x >= 1 and mouse_pos.x <= width:
                    current_bounds = (
                        layer._overlays["roi_box"].bounds[0],
                        (mouse_pos.x, layer._overlays["roi_box"].bounds[1][1]),
                    )
            case InteractionBoxHandle.TOP_LEFT:
                if (mouse_pos.y >= 0 and mouse_pos.y <= height - 1) and (
                    mouse_pos.x >= 0 and mouse_pos.x <= width - 1
                ):
                    print("top left not implemented", mouse_pos)
            case InteractionBoxHandle.TOP_RIGHT:
                if (mouse_pos.y >= 0 and mouse_pos.y <= height - 1) and (
                    mouse_pos.x >= 1 and mouse_pos.x <= width
                ):
                    print("top right not implemented", mouse_pos)
            case InteractionBoxHandle.TOP_CENTER:
                if mouse_pos.y >= 0 and mouse_pos.y <= height - 1:
                    current_bounds = (
                        (layer._overlays["roi_box"].bounds[0][0], mouse_pos.y),
                        layer._overlays["roi_box"].bounds[1],
                    )
            case InteractionBoxHandle.BOTTOM_CENTER:
                if mouse_pos.y >= 1 and mouse_pos.y <= height:
                    current_bounds = (
                        (layer._overlays["roi_box"].bounds[0][0], mouse_pos.y),
                        layer._overlays["roi_box"].bounds[1],
                    )
            case InteractionBoxHandle.BOTTOM_LEFT:
                if (mouse_pos.y >= 1 and mouse_pos.y <= height) and (
                    mouse_pos.x >= 0 and mouse_pos.x <= width - 1
                ):
                    print("bottom left not implemented", mouse_pos)
            case InteractionBoxHandle.BOTTOM_RIGHT:
                if (mouse_pos.y >= 1 and mouse_pos.y <= height) and (
                    mouse_pos.x >= 1 and mouse_pos.x <= width
                ):
                    print("bottom right not implemented", mouse_pos)

            case _:  # fallback on other handles, do nothing
                current_bounds = deepcopy(layer._overlays["roi_box"].bounds)

        layer._overlays["roi_box"].bounds = deepcopy(current_bounds)
        yield


def highlight_roi_box_handles(layer: Image, event: NapariMouseEvent) -> None:
    """Highlight the hovered handle of a ROI.

    Parameters
    ----------
    layer : Image
        The layer to highlight the ROI box for.
    event : NapariMouseEvent
        The event triggered by mouse movement.
    """
    if len(event.dims_displayed) != 2:
        return

    # we work in data space so we're axis aligned which simplifies calculation
    # same as Layer.world_to_data
    world_to_data = (
        layer._transforms[1:].set_slice(layer._slice_input.displayed).inverse
    )
    pos = np.array(world_to_data(event.position))[event.dims_displayed]

    handle_coords = generate_interaction_box_vertices(
        *layer._overlays["roi_box"].bounds, handles=True
    )[:, ::-1]
    nearby_handle = get_nearby_handle(pos, handle_coords)
    if nearby_handle in [InteractionBoxHandle.INSIDE, InteractionBoxHandle.ROTATION]:
        return

    # set the selected vertex of the box to the nearby_handle (can also be INSIDE or None)
    layer._overlays["roi_box"].selected_handle = nearby_handle
