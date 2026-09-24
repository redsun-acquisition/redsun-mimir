from __future__ import annotations

from typing import TYPE_CHECKING

from napari._app_model import get_app_model
from napari._qt._qapp_model.injection._qproviders import register_qt_types
from napari._qt.qt_viewer import QtViewer  # noqa: TC002
from napari.components import LayerList, ViewerModel  # noqa: TC002
from napari.layers import Layer  # noqa: TC002
from napari.utils._proxies import PublicOnlyProxy
from napari.utils.events.containers._selection import Selection  # noqa: TC002

if TYPE_CHECKING:
    from in_n_out._store import InjectionContext


def register_embedded_viewer(
    viewer_model: ViewerModel, qt_viewer: QtViewer
) -> InjectionContext:
    """Make napari's actions and menus act on an embedded viewer.

    napari's own providers find the viewer, its layers and its selection
    through the current ``Viewer`` window, which an embedded `ViewerModel`
    never becomes; without these, the layer list's context menu raises.
    Call ``cleanup()`` on the result when the viewer is closed.
    """
    register_qt_types()
    # napari hands its callbacks a proxy that warns on private access
    proxy: ViewerModel = PublicOnlyProxy(viewer_model)

    # the store reads each provider's return annotation at runtime
    def provide_viewer() -> ViewerModel | None:
        return proxy

    def provide_qt_viewer() -> QtViewer | None:
        return qt_viewer

    def provide_layers() -> LayerList | None:
        return proxy.layers

    def provide_active_layer() -> Layer | None:
        return proxy.layers.selection.active

    def provide_selection() -> Selection[Layer] | None:
        return proxy.layers.selection

    context: InjectionContext = get_app_model().injection_store.register(
        providers=[
            (provide_viewer,),
            (provide_qt_viewer,),
            (provide_layers,),
            (provide_active_layer,),
            (provide_selection,),
        ],
    )
    return context
