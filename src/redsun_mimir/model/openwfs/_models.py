from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .._config import StageModelInfo


class OWFSStage:
    def __init__(self, name: str, model_info: StageModelInfo) -> None: ...
