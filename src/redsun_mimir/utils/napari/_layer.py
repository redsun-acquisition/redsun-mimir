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

from collections import defaultdict
from typing import TYPE_CHECKING, Callable, ClassVar, Generator

import numpy as np
from napari.layers import Image as NapariImage
from napari.layers import Layer
from napari.layers.base import no_op
from napari.layers.base._base_mouse_bindings import (
    highlight_box_handles,
    transform_with_box,
)
from napari.utils.events import Event

from ._common import ExtendedMode
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

    # Get the coordinates in data space
    world_to_data = (
        layer._transforms[1:].set_slice(layer._slice_input.displayed).inverse
    )

    # Start position in data coordinates
    start_position = np.array(world_to_data(event.position))[event.dims_displayed]
    last_position = start_position.copy()

    # Get the current bounds of the ROI box
    current_bounds = layer.roi.bounds
    top_left = np.array(current_bounds[0])
    bot_right = np.array(current_bounds[1])

    # Layer bounds for clipping
    layer_bounds = np.array([(0, 0), layer.full_size])
    min_bounds = layer_bounds[0]
    max_bounds = layer_bounds[1]

    # Track if we've hit the 1-pixel threshold
    threshold_hit = {"left": False, "right": False, "top": False, "bottom": False}

    # The minimum distance from border to consider "at threshold"
    pixel_threshold = 1.0

    # Determine which bound coordinates this handle affects
    affects_left = selected_handle in (
        ROIInteractionBoxHandle.TOP_LEFT,
        ROIInteractionBoxHandle.CENTER_LEFT,
        ROIInteractionBoxHandle.BOTTOM_LEFT,
    )
    affects_right = selected_handle in (
        ROIInteractionBoxHandle.TOP_RIGHT,
        ROIInteractionBoxHandle.CENTER_RIGHT,
        ROIInteractionBoxHandle.BOTTOM_RIGHT,
    )
    affects_top = selected_handle in (
        ROIInteractionBoxHandle.TOP_LEFT,
        ROIInteractionBoxHandle.TOP_CENTER,
        ROIInteractionBoxHandle.TOP_RIGHT,
    )
    affects_bottom = selected_handle in (
        ROIInteractionBoxHandle.BOTTOM_LEFT,
        ROIInteractionBoxHandle.BOTTOM_CENTER,
        ROIInteractionBoxHandle.BOTTOM_RIGHT,
    )

    yield

    # Main event loop for handling drag events
    while event.type == "mouse_move":
        current_position = np.array(world_to_data(event.position))[event.dims_displayed]
        print(current_position)

        # Calculate how much the mouse has moved since last position
        delta = current_position - last_position

        # Update bounds based on handle movement
        new_top_left = top_left.copy()
        new_bot_right = bot_right.copy()

        # Update X coordinates (left/right)
        if affects_left:
            new_top_left[0] += delta[0]

            # Handle 1-pixel threshold for left edge
            if abs(new_top_left[0] - min_bounds[0]) <= pixel_threshold:
                if delta[0] < 0 or threshold_hit["left"]:
                    new_top_left[0] = min_bounds[0]
                    threshold_hit["left"] = True

            # If moving away from threshold
            elif threshold_hit["left"] and delta[0] > 0:
                threshold_hit["left"] = False

        if affects_right:
            new_bot_right[0] += delta[0]

            # Handle 1-pixel threshold for right edge
            if abs(new_bot_right[0] - max_bounds[0]) <= pixel_threshold:
                if delta[0] > 0 or threshold_hit["right"]:
                    new_bot_right[0] = max_bounds[0]
                    threshold_hit["right"] = True

            # If moving away from threshold
            elif threshold_hit["right"] and delta[0] < 0:
                threshold_hit["right"] = False

        # Update Y coordinates (top/bottom)
        if affects_top:
            new_top_left[1] += delta[1]

            # Handle 1-pixel threshold for top edge
            if abs(new_top_left[1] - min_bounds[1]) <= pixel_threshold:
                if delta[1] < 0 or threshold_hit["top"]:
                    new_top_left[1] = min_bounds[1]
                    threshold_hit["top"] = True

            # If moving away from threshold
            elif threshold_hit["top"] and delta[1] > 0:
                threshold_hit["top"] = False

        if affects_bottom:
            new_bot_right[1] += delta[1]

            # Handle 1-pixel threshold for bottom edge
            if abs(new_bot_right[1] - max_bounds[1]) <= pixel_threshold:
                if delta[1] > 0 or threshold_hit["bottom"]:
                    new_bot_right[1] = max_bounds[1]
                    threshold_hit["bottom"] = True

            # If moving away from threshold
            elif threshold_hit["bottom"] and delta[1] < 0:
                threshold_hit["bottom"] = False

        # Ensure box doesn't flip (left is always left of right, top always above bottom)
        if new_top_left[0] > new_bot_right[0]:
            if affects_left:
                new_top_left[0] = new_bot_right[0]
            else:
                new_bot_right[0] = new_top_left[0]

        if new_top_left[1] > new_bot_right[1]:
            if affects_top:
                new_top_left[1] = new_bot_right[1]
            else:
                new_bot_right[1] = new_top_left[1]

        # Clip to layer bounds
        new_top_left = np.clip(new_top_left, min_bounds, max_bounds)
        new_bot_right = np.clip(new_bot_right, min_bounds, max_bounds)

        # Update the ROI box bounds
        layer.roi.bounds = (tuple(new_top_left), tuple(new_bot_right))

        # Remember the current position for next delta calculation
        last_position = current_position

        yield

    # Final update - ensure we're still within layer bounds
    top_left, bot_right = layer.roi.bounds
    top_left_arr = np.array(top_left)
    bot_right_arr = np.array(bot_right)

    top_left_arr = np.clip(top_left_arr, min_bounds, max_bounds)
    bot_right_arr = np.clip(bot_right_arr, min_bounds, max_bounds)

    layer.roi.bounds = (tuple(top_left_arr), tuple(bot_right_arr))


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


class DetectorLayer(NapariImage):  # type: ignore[misc]
    """Layer for displaying data from a 2D detector (i.e. a camera)."""

    ModeCallable = Callable[[Layer, Event], None] | Generator[None, None, None]

    _modeclass: ClassVar[type[ExtendedMode]] = ExtendedMode
    _mode: ExtendedMode

    _drag_modes: ClassVar[dict[ExtendedMode, ModeCallable]] = {
        ExtendedMode.PAN_ZOOM: no_op,  # type: ignore[dict-item]
        ExtendedMode.TRANSFORM: transform_with_box,  # type: ignore[dict-item]
        ExtendedMode.RESIZE: resize_roi_box,  # type: ignore[dict-item]
    }

    _move_modes: ClassVar[dict[ExtendedMode, ModeCallable]] = {
        ExtendedMode.PAN_ZOOM: no_op,  # type: ignore[dict-item]
        ExtendedMode.TRANSFORM: highlight_box_handles,  # type: ignore[dict-item]
        ExtendedMode.RESIZE: highlight_roi_box_handles,  # type: ignore[dict-item]
    }

    _cursor_modes: ClassVar[dict[ExtendedMode, str]] = {
        ExtendedMode.PAN_ZOOM: "standard",  # type: ignore[dict-item]
        ExtendedMode.TRANSFORM: "standard",  # type: ignore[dict-item]
        ExtendedMode.RESIZE: "standard",  # type: ignore[dict-item]
    }

    def _post_init(self) -> None:
        """Add a ROI box overlay to the layer after initialization."""
        self._full_size = (self.data.shape[1], self.data.shape[0])
        overlay = ROIInteractionBoxOverlay(
            bounds=((0, 0), (self.data.shape[1], self.data.shape[0])),
        )
        self._overlays.update({"roi_box": overlay})

    def _mode_setter_helper(self, mode_in: ExtendedMode | str) -> ExtendedMode:
        """Manage mode setting callbacks in multiple layers.

        This will return a valid mode for the current layer, to for example
        refuse to set a mode that is not supported by the layer if it is not editable.

        This will as well manage the mouse callbacks.


        Parameters
        ----------
        mode : ExtendedMode | str
            New mode for the current layer.

        Returns
        -------
        mode : ExtendedMode
            New mode for the current layer.

        """
        mode = self._modeclass(mode_in)
        if not self.editable or not self.visible:
            # if the layer is not editable or not visible, set the mode to PAN_ZOOM
            mode = ExtendedMode.PAN_ZOOM  # type: ignore[assignment]
        if mode == self._mode:
            return mode
        if mode not in self._modeclass:  # type: ignore[attr-defined]
            raise ValueError("Mode not recognized: {mode}", deferred=True, mode=mode)  # type: ignore[call-arg]

        for callback_list, mode_dict in [
            (self.mouse_drag_callbacks, self._drag_modes),
            (self.mouse_move_callbacks, self._move_modes),
            (
                self.mouse_double_click_callbacks,
                getattr(self, "_double_click_modes", defaultdict(lambda: no_op)),
            ),
        ]:
            if mode_dict[self._mode] in callback_list:
                callback_list.remove(mode_dict[self._mode])
            callback_list.append(mode_dict[mode])
        self.cursor = self._cursor_modes[mode]

        self.mouse_pan = mode == ExtendedMode.PAN_ZOOM
        self._overlays["transform_box"].visible = mode == ExtendedMode.TRANSFORM

        if mode == ExtendedMode.TRANSFORM:
            self.help = "hold <space> to move camera, hold <shift> to preserve aspect ratio and rotate in 45° increments"
        elif mode == ExtendedMode.RESIZE:
            self.help = "move the handles to resize the current layer visible region"
        elif mode == ExtendedMode.PAN_ZOOM:
            self.help = ""

        return mode

    def update_transform_box_visibility(self, visible: bool) -> None:
        if "transform_box" in self._overlays:
            self._overlays["transform_box"].visible = (
                self.mode == ExtendedMode.TRANSFORM and visible
            )

    @property
    def mode(self) -> str:
        """str: Interactive mode.

        Interactive mode. The normal, default mode is PAN_ZOOM, which
        allows for normal interactivity with the canvas.

        TRANSFORM allows for manipulation of the layer transform.

        RESIZE allows for manipulation of the layer overlay ROI box.
        """
        return str(self._mode)

    @mode.setter
    def mode(self, mode: ExtendedMode | str) -> None:
        mode_enum = self._mode_setter_helper(mode)
        if mode_enum == self._mode:
            return
        self._mode = mode_enum

        self.events.mode(mode=str(mode_enum))

    @property
    def roi(self) -> ROIInteractionBoxOverlay:
        """Returns the ROI box overlay."""
        return self._overlays["roi_box"]  # type: ignore[no-any-return]

    @property
    def full_size(self) -> tuple[int, int]:
        """Returns the full size of the layer in width and height."""
        return self._full_size
