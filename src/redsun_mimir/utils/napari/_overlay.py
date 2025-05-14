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

from enum import IntEnum
from functools import lru_cache
from typing import TYPE_CHECKING

import numpy as np
from napari._vispy.overlays.base import LayerOverlayMixin, VispySceneOverlay
from napari._vispy.visuals.markers import Markers
from napari.components.overlays.base import SceneOverlay
from napari.layers.utils.interaction_box import (
    calculate_bounds_from_contained_points,
)
from vispy.scene.visuals import Compound, Line

if TYPE_CHECKING:
    from typing import Any

    import numpy.typing as npt
    from napari.layers import Image


@lru_cache
def generate_roi_box_vertices(
    top_left: tuple[float, float],
    bot_right: tuple[float, float],
) -> npt.NDArray[Any]:
    """
    Generate coordinates for all the handles in ROIInteractionBoxHandle.

    Coordinates are assumed to follow vispy "y down" convention.

    Parameters
    ----------
    top_left : Tuple[float, float]
        Top-left corner of the box
    bot_right : Tuple[float, float]
        Bottom-right corner of the box
    handles : bool
        Whether to also return indices for the transformation handles.

    Returns
    -------
    np.ndarray
        Coordinates of the vertices and handles of the interaction box.
    """
    x0, y0 = top_left
    x1, y1 = bot_right
    vertices = np.array(
        [
            [x0, y0],
            [x0, y1],
            [x1, y0],
            [x1, y1],
        ]
    )

    # add handles at the midpoint of each side
    middle_vertices = np.mean([vertices, vertices[[2, 0, 3, 1]]], axis=0)
    vertices = np.concatenate([vertices, middle_vertices])

    return vertices


def get_nearby_roi_handle(
    position: npt.NDArray[Any], handle_coordinates: npt.NDArray[Any]
) -> ROIInteractionBoxHandle | None:
    """
    Get the ROIInteractionBoxHandle close to the given position, within tolerance.

    Parameters
    ----------
    position : npt.NDArray[Any]
        Position to query for.
    handle_coordinates : npt.NDArray[Any]
        Coordinates of all the handles (except INSIDE).

    Returns
    -------
    Optional[ROIInteractionBoxHandle]
        The nearby handle if any.
    """
    dist: npt.NDArray[Any] = np.linalg.norm(position - handle_coordinates, axis=1)
    tolerance = dist.max() / 100
    close_to_vertex = np.isclose(dist, 0, atol=tolerance)
    if np.any(close_to_vertex):
        idx = int(np.argmax(close_to_vertex))
        return ROIInteractionBoxHandle(idx)
    return None


class ROIInteractionBoxHandle(IntEnum):
    """
    Handle indices for the InteractionBox overlay.

    Vertices are generated according to the following scheme:
    0---4---2
    |       |
    5       6
    |       |
    1---7---3

    Note that y is actually upside down in the canvas in vispy coordinates.
    """

    TOP_LEFT = 0
    TOP_CENTER = 4
    TOP_RIGHT = 2
    CENTER_LEFT = 5
    CENTER_RIGHT = 6
    BOTTOM_LEFT = 1
    BOTTOM_CENTER = 7
    BOTTOM_RIGHT = 3

    @classmethod
    def opposite_handle(
        cls, handle: ROIInteractionBoxHandle
    ) -> ROIInteractionBoxHandle:
        opposites = {
            cls.TOP_LEFT: cls.BOTTOM_RIGHT,
            cls.TOP_CENTER: cls.BOTTOM_CENTER,
            cls.TOP_RIGHT: cls.BOTTOM_LEFT,
            cls.CENTER_LEFT: cls.CENTER_RIGHT,
            cls.BOTTOM_LEFT: cls.TOP_RIGHT,
            cls.BOTTOM_CENTER: cls.TOP_CENTER,
            cls.BOTTOM_RIGHT: cls.TOP_LEFT,
            cls.CENTER_RIGHT: cls.CENTER_LEFT,
        }

        if (opposite := opposites.get(handle)) is None:
            raise ValueError(f"{handle} has no opposite handle.")
        return opposite

    @classmethod
    def corners(
        cls,
    ) -> tuple[
        ROIInteractionBoxHandle,
        ROIInteractionBoxHandle,
        ROIInteractionBoxHandle,
        ROIInteractionBoxHandle,
    ]:
        return (
            cls.TOP_LEFT,
            cls.TOP_RIGHT,
            cls.BOTTOM_LEFT,
            cls.BOTTOM_RIGHT,
        )


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
    selected_handle: ROIInteractionBoxHandle | None = None

    def update_from_points(self, points: npt.NDArray[Any]) -> None:
        """Create as a bounding box of the given points."""
        self.bounds = calculate_bounds_from_contained_points(points)


class ROIBoxNode(Compound):  # type: ignore[misc]
    # vertices are generated according to the following scheme:
    # (y is actually upside down in the canvas)
    #  0---4---2    1 = position
    #  |       |
    #  5       6
    #  |       |
    #  1---7---3
    _edges = np.array(
        [
            [0, 1],
            [1, 3],
            [1, 3],
            [2, 0],
            [4, 8],
        ]
    )

    def __init__(self) -> None:
        self._marker_color = (1, 1, 1, 1)
        self._marker_size = 10
        self._highlight_width = 2

        # squares for corners and midpoints
        self._marker_symbol = ["square"] * 8
        self._edge_color = (0, 0, 1, 1)

        super().__init__([Line(), Markers(antialias=0)])

    @property
    def line(self) -> Line:
        return self._subvisuals[0]

    @property
    def markers(self) -> Markers:
        return self._subvisuals[1]

    def set_data(
        self,
        top_left: tuple[float, float],
        bot_right: tuple[float, float],
        selected: int | None = None,
    ) -> None:
        vertices = generate_roi_box_vertices(top_left, bot_right)

        self.line.set_data(pos=vertices, connect=self._edges)

        marker_edges = np.zeros(len(vertices))
        if selected is not None:
            marker_edges[selected] = self._highlight_width

        self.markers.set_data(
            pos=vertices,
            size=self._marker_size,
            face_color=self._marker_color,
            symbol=self._marker_symbol,
            edge_width=marker_edges,
            edge_color=self._edge_color,
        )


class VispyROIBoxOverlay(LayerOverlayMixin, VispySceneOverlay):  # type: ignore[misc]
    node: ROIBoxNode
    overlay: ROIInteractionBoxOverlay
    layer: Image

    def __init__(self, *, layer: Image, overlay: ROIBoxNode, parent=None) -> None:  # type: ignore[no-untyped-def]
        super().__init__(node=ROIBoxNode(), layer=layer, overlay=overlay, parent=parent)
        self.layer.events.set_data.connect(self._on_visible_change)
        self.overlay.events.bounds.connect(self._on_bounds_change)
        self.overlay.events.selected_handle.connect(self._on_bounds_change)

    def _on_bounds_change(self) -> None:
        if self.layer._slice_input.ndisplay == 2:
            bounds = self.layer._display_bounding_box_augmented_data_level(
                self.layer._slice_input.displayed
            )

            # invert axes for vispy
            print(bounds)
            top_left, bot_right = (tuple(point) for point in bounds.T[:, ::-1])

            self.node.set_data(
                top_left, bot_right, selected=self.overlay.selected_handle
            )

    def _on_visible_change(self) -> None:
        if self.layer._slice_input.ndisplay == 2:
            super()._on_visible_change()
        else:
            self.node.visible = False

    def reset(self) -> None:
        super().reset()
        self._on_bounds_change()
