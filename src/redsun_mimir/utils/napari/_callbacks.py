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
from typing import TYPE_CHECKING

import numpy as np
from napari.components.overlays.interaction_box import InteractionBoxHandle
from napari.layers.utils.interaction_box import (
    generate_interaction_box_vertices,
    get_nearby_handle,
)

if TYPE_CHECKING:
    from typing import Generator

    from napari._vispy.mouse_event import NapariMouseEvent
    from napari.layers import Image


def resize_selection_box(
    layer: Image, event: NapariMouseEvent
) -> Generator[None, None, None]:
    """Resize the selection box based on mouse movement.

    Parameters
    ----------
    layer : DetectorLayer
        The layer to resize the selection box for.
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
        # If no handle is selected or the selected handle
        # is INSIDE or ROTATION, do nothing
        return

    top_left, bot_right = (list(x) for x in deepcopy(layer._overlays["roi_box"].bounds))

    layer_bounds = layer._display_bounding_box_augmented([0, 1])

    event.handled = True

    yield

    while event.type == "mouse_move":
        mouse_pos = layer.world_to_data(event.position)[event.dims_displayed]
        clipped_y = np.clip(mouse_pos[0], *layer_bounds[0])
        clipped_x = np.clip(mouse_pos[1], *layer_bounds[1])

        match selected_handle:
            case InteractionBoxHandle.TOP_LEFT:
                top_left[0] = clipped_y
                top_left[1] = clipped_x
            case InteractionBoxHandle.TOP_CENTER:
                top_left[0] = clipped_y
            case InteractionBoxHandle.TOP_RIGHT:
                top_left[0] = clipped_y
                bot_right[1] = clipped_x
            case InteractionBoxHandle.CENTER_LEFT:
                top_left[1] = clipped_x
            case InteractionBoxHandle.CENTER_RIGHT:
                bot_right[1] = clipped_x
            case InteractionBoxHandle.BOTTOM_LEFT:
                bot_right[0] = clipped_y
                top_left[1] = clipped_x
            case InteractionBoxHandle.BOTTOM_CENTER:
                bot_right[0] = clipped_y
            case InteractionBoxHandle.BOTTOM_RIGHT:
                bot_right[0] = clipped_y
                bot_right[1] = clipped_x
            case _:
                pass

        layer._overlays["roi_box"].bounds = deepcopy(
            (tuple(top_left), tuple(bot_right))
        )
        yield


def highlight_roi_box_handles(layer: Image, event: NapariMouseEvent) -> None:
    """Highlight the hovered handle of a selection box.

    Parameters
    ----------
    layer : Image
        The layer to highlight the selection box for.
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

    # interaction box calculations all happen in vispy coordinates (zyx)
    pos = np.array(world_to_data(event.position))[event.dims_displayed][::-1]

    top_left, bot_right = layer._overlays["roi_box"].bounds
    handle_coords = generate_interaction_box_vertices(
        top_left[::-1], bot_right[::-1], handles=True
    )
    nearby_handle = get_nearby_handle(pos, handle_coords)

    # if the selected handle is INSIDE or ROTATION, we don't want to
    # highlight the handles, so we set nearby_handle to None
    if nearby_handle in [
        InteractionBoxHandle.INSIDE,
        InteractionBoxHandle.ROTATION,
    ]:
        nearby_handle = None

    layer._overlays["roi_box"].selected_handle = nearby_handle
