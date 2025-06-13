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

from napari._vispy.overlays.interaction_box import VispySelectionBoxOverlay
from napari.components.overlays import SelectionBoxOverlay

if TYPE_CHECKING:
    from napari._vispy.overlays.interaction_box import InteractionBox
    from napari.layers import Image


class ROIInteractionBoxOverlay(SelectionBoxOverlay):  # type: ignore[misc]
    """A box to select a region of interest in an image.

    Attributes
    ----------
    bounds : 2-tuple of 2-tuples
        Corners at top left and bottom right in layer coordinates.
    handles : bool
        Whether to show the handles for transfomation or just the box.
    selected_handle : Optional[InteractionBoxHandle]
        The currently selected handle.
    visible : bool
        If the overlay is visible or not.
    opacity : float
        The opacity of the overlay. 0 is fully transparent.
    order : int
        The rendering order of the overlay: lower numbers get rendered first.

    Notes
    -----
    The attributes are inherited from `SelectionBoxOverlay`.
    """


class VispyROIBoxOverlay(VispySelectionBoxOverlay):  # type: ignore[misc]
    """Vispy overlay, connected to an assigne Image layer and its associated ROIInteractionBoxOverlay.

    Provides a visual representation of the region of interest (ROI) of the image layer.
    """

    node: InteractionBox
    overlay: ROIInteractionBoxOverlay
    layer: Image

    def _on_bounds_change(self) -> None:
        if self.layer._slice_input.ndisplay == 2:
            top_left, bot_right = self.overlay.bounds
            self.node.set_data(
                # invert axes for vispy
                top_left[::-1],
                bot_right[::-1],
                handles=self.overlay.handles,
                selected=self.overlay.selected_handle,
                rotation=False,
            )
