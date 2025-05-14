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
from copy import deepcopy
from typing import TYPE_CHECKING, Callable, ClassVar, Generator, NamedTuple

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
    current_bounds = deepcopy(layer.roi.bounds)

    yield

    # Main event loop for handling drag events
    while event.type == "mouse_move":
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
    def width(self) -> int:
        """Returns the width of the layer."""
        return self._full_size[0]

    @property
    def height(self) -> int:
        """Returns the height of the layer."""
        return self._full_size[1]
