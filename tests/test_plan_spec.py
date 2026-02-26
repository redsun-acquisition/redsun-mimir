"""Smoke tests for plan-spec inspection and widget factory logic.

Covers:
- ``utils.isdevice`` / ``utils.isdevicesequence`` / ``utils.issequence``
- ``common.create_plan_spec``: correct field population for each annotation shape
- ``common.create_plan_spec``: ``UnresolvableAnnotationError`` for required
  parameters whose annotation cannot be mapped to a widget
- ``common.collect_arguments`` / ``common.resolve_arguments``
- ``common._plan_spec._dispatch_annotation``: dispatch table entry selection
- ``utils.qt.create_param_widget``: factory registry — correct widget type
  per ``ParamDescription``
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from inspect import Parameter
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import pytest
from bluesky.utils import MsgGenerator

from redsun_mimir.actions import Action
from redsun_mimir.common import (
    ParamDescription,
    ParamKind,
    PlanSpec,
    UnresolvableAnnotationError,
    collect_arguments,
    create_plan_spec,
    resolve_arguments,
)
from redsun_mimir.common._plan_spec import _dispatch_annotation, _FieldsFromAnnotation
from redsun_mimir.device._mocks import MockMotorDevice
from redsun_mimir.protocols import DetectorProtocol, MotorProtocol
from redsun_mimir.utils import isdevice, isdevicesequence, issequence

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# Helpers: minimal mock devices that satisfy runtime-checkable protocols
# ---------------------------------------------------------------------------


class _MockDetector:
    """Minimal structural mock that satisfies ``DetectorProtocol``."""

    name: str
    parent = None
    roi = (0, 0, 512, 512)
    sensor_shape = (512, 512)

    def __init__(self, name: str) -> None:
        self.name = name

    def describe_configuration(self) -> dict:
        return {}

    def read_configuration(self) -> dict:
        return {}

    def describe(self) -> dict:
        return {}

    def read(self) -> dict:
        return {}

    def stage(self) -> list:
        return []

    def unstage(self) -> list:
        return []

    def set(self, value: object) -> object:
        return None


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def one_detector() -> dict[str, _MockDetector]:
    return {"cam": _MockDetector("cam")}


@pytest.fixture
def one_motor(mock_motor: MockMotorDevice) -> dict[str, MockMotorDevice]:
    return {"stage": mock_motor}


# ---------------------------------------------------------------------------
# utils: isdevice / isdevicesequence / issequence
# ---------------------------------------------------------------------------


class TestTypePredicates:
    """Unit tests for the annotation-classification helpers in ``utils``."""

    def test_isdevice_true_for_detector_protocol(self) -> None:
        assert isdevice(DetectorProtocol)

    def test_isdevice_true_for_motor_protocol(self) -> None:
        assert isdevice(MotorProtocol)

    def test_isdevice_false_for_primitive(self) -> None:
        assert not isdevice(int)
        assert not isdevice(str)
        assert not isdevice(float)

    def test_isdevice_false_for_instance(self) -> None:
        """isdevice operates on type annotations, not instances."""
        assert not isdevice(42)
        assert not isdevice("hello")

    def test_isdevicesequence_true(self) -> None:
        assert isdevicesequence(Sequence[DetectorProtocol])
        assert isdevicesequence(Sequence[MotorProtocol])

    def test_isdevicesequence_false_for_primitive_sequence(self) -> None:
        assert not isdevicesequence(Sequence[int])
        assert not isdevicesequence(Sequence[str])

    def test_isdevicesequence_false_for_bare_type(self) -> None:
        assert not isdevicesequence(DetectorProtocol)

    def test_issequence_true_for_generic_alias(self) -> None:
        assert issequence(Sequence[int])
        assert issequence(list[float])

    def test_issequence_false_for_str(self) -> None:
        """str is NOT returned as a generic alias by get_origin."""
        assert not issequence(str)

    def test_issequence_false_for_bare_class(self) -> None:
        assert not issequence(int)


# ---------------------------------------------------------------------------
# create_plan_spec: annotation dispatch
# ---------------------------------------------------------------------------


class TestCreatePlanSpec:
    """Tests for ``create_plan_spec`` across the supported annotation shapes."""

    # ---- primitive / magicgui-native types --------------------------------

    def test_int_param(self) -> None:
        def plan(x: int) -> MsgGenerator[None]:
            yield  # type: ignore

        spec = create_plan_spec(plan, {})
        p = spec.parameters[0]
        assert p.name == "x"
        assert p.annotation is int
        assert p.choices is None
        assert p.device_proto is None

    def test_float_param_with_default(self) -> None:
        def plan(step: float = 1.0) -> MsgGenerator[None]:
            yield  # type: ignore

        spec = create_plan_spec(plan, {})
        p = spec.parameters[0]
        assert p.has_default
        assert p.default == pytest.approx(1.0)

    # ---- Literal ----------------------------------------------------------

    def test_literal_produces_string_choices(self) -> None:
        def plan(egu: Literal["um", "mm", "nm"] = "um") -> MsgGenerator[None]:
            yield  # type: ignore

        spec = create_plan_spec(plan, {})
        p = spec.parameters[0]
        assert p.choices == ["um", "mm", "nm"]
        assert p.device_proto is None
        assert not p.multiselect

    def test_literal_with_int_values_stringified(self) -> None:
        def plan(n: Literal[1, 2, 3] = 1) -> MsgGenerator[None]:
            yield  # type: ignore

        spec = create_plan_spec(plan, {})
        assert spec.parameters[0].choices == ["1", "2", "3"]

    # ---- PDevice single ---------------------------------------------------

    def test_single_device_param_populates_choices(
        self, one_motor: dict[str, MockMotorDevice]
    ) -> None:
        def plan(motor: MotorProtocol) -> MsgGenerator[None]:
            yield  # type: ignore

        spec = create_plan_spec(plan, one_motor)
        p = spec.parameters[0]
        assert p.choices == ["stage"]
        assert not p.multiselect
        assert p.device_proto is MotorProtocol

    def test_single_device_no_registry_match_raises(self) -> None:
        """A required PDevice parameter with no matching devices is unresolvable.

        The plan cannot be driven from the UI without at least one matching
        device in the registry, so ``create_plan_spec`` raises rather than
        producing a param with ``choices=None`` that would silently break.
        """

        def plan(motor: MotorProtocol) -> MsgGenerator[None]:
            yield  # type: ignore

        with pytest.raises(UnresolvableAnnotationError) as exc_info:
            create_plan_spec(plan, {})
        assert exc_info.value.param_name == "motor"

    def test_single_device_no_registry_match_ok_with_default(self) -> None:
        """A PDevice param with a default is fine even with an empty registry."""

        def plan(motor: MotorProtocol = None) -> MsgGenerator[None]:  # type: ignore[assignment]
            yield  # type: ignore

        spec = create_plan_spec(plan, {})
        assert spec.parameters[0].choices is None  # no match, but has default

    # ---- Sequence[PDevice] ------------------------------------------------

    def test_sequence_device_param_is_multiselect(
        self, one_detector: dict[str, _MockDetector]
    ) -> None:
        def plan(dets: Sequence[DetectorProtocol]) -> MsgGenerator[None]:
            yield  # type: ignore

        spec = create_plan_spec(plan, one_detector)
        p = spec.parameters[0]
        assert p.choices == ["cam"]
        assert p.multiselect
        assert p.device_proto is DetectorProtocol

    # ---- VAR_POSITIONAL device (*args) ------------------------------------

    def test_var_positional_device_is_multiselect(
        self, one_detector: dict[str, _MockDetector]
    ) -> None:
        def plan(*dets: DetectorProtocol) -> MsgGenerator[None]:
            yield  # type: ignore

        spec = create_plan_spec(plan, one_detector)
        p = spec.parameters[0]
        assert p.kind is ParamKind.VAR_POSITIONAL
        assert p.choices == ["cam"]
        assert p.multiselect

    # ---- Action parameters ------------------------------------------------

    def test_action_param_has_no_choices_and_stores_meta(self) -> None:
        @dataclass
        class Snap(Action):
            name: str = "snap"

        def plan(frames: int = 1, /, snap: Action = Snap()) -> MsgGenerator[None]:
            yield  # type: ignore

        spec = create_plan_spec(plan, {})
        action_p = next(p for p in spec.parameters if p.name == "snap")
        assert action_p.actions is not None
        assert isinstance(action_p.actions, Action)
        assert action_p.choices is None

    def test_action_sequence_param(self) -> None:
        @dataclass
        class A(Action):
            name: str = "a"

        @dataclass
        class B(Action):
            name: str = "b"

        def plan(
            frames: int = 1,
            /,
            actions: Action = [A(), B()],  # type: ignore[assignment]
        ) -> MsgGenerator[None]:
            yield  # type: ignore

        spec = create_plan_spec(plan, {})
        p = next(q for q in spec.parameters if q.name == "actions")
        assert isinstance(p.actions, list)
        assert len(p.actions) == 2

    # ---- toggleable / pausable flags --------------------------------------

    def test_togglable_flag(self) -> None:
        from redsun_mimir.actions import continous

        @continous(togglable=True, pausable=True)
        def plan() -> MsgGenerator[None]:  # type: ignore[misc]
            yield  # type: ignore

        spec = create_plan_spec(plan, {})
        assert spec.togglable is True
        assert spec.pausable is True

    def test_non_togglable_plan(self) -> None:
        def plan(x: int) -> MsgGenerator[None]:
            yield  # type: ignore

        spec = create_plan_spec(plan, {})
        assert spec.togglable is False
        assert spec.pausable is False

    # ---- self/cls stripping -----------------------------------------------

    def test_self_is_stripped_from_method_signature(self) -> None:
        class Presenter:
            def plan(self, x: int) -> MsgGenerator[None]:
                yield  # type: ignore

        spec = create_plan_spec(Presenter.plan, {})
        assert all(p.name != "self" for p in spec.parameters)
        assert spec.parameters[0].name == "x"

    # ---- error cases -------------------------------------------------------

    def test_non_generator_raises_type_error(self) -> None:
        def not_a_plan(x: int) -> int:
            return x

        with pytest.raises(TypeError, match="generator function"):
            create_plan_spec(not_a_plan, {})  # type: ignore[arg-type]

    def test_missing_return_annotation_raises(self) -> None:
        def plan(x: int):  # type: ignore[no-untyped-def]
            yield

        with pytest.raises(TypeError, match="return type annotation"):
            create_plan_spec(plan, {})  # type: ignore[arg-type]

    def test_wrong_return_type_raises(self) -> None:
        def plan(x: int) -> list[int]:  # not a generator
            yield x  # type: ignore[misc]

        with pytest.raises(TypeError, match="MsgGenerator"):
            create_plan_spec(plan, {})  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# UnresolvableAnnotationError
# ---------------------------------------------------------------------------


class TestUnresolvableAnnotation:
    """Tests for the Option-B unresolvable-annotation guard."""

    class _Exotic:
        """A type magicgui has no idea how to handle."""

    def test_required_exotic_param_raises(self) -> None:
        def bad_plan(thing: TestUnresolvableAnnotation._Exotic) -> MsgGenerator[None]:
            yield  # type: ignore

        with pytest.raises(UnresolvableAnnotationError) as exc_info:
            create_plan_spec(bad_plan, {})

        err = exc_info.value
        assert err.param_name == "thing"
        assert err.plan_name == "bad_plan"
        assert err.annotation is TestUnresolvableAnnotation._Exotic

    def test_optional_exotic_param_does_not_raise(self) -> None:
        """A param with a default value is never required — plan should succeed."""
        default_val = TestUnresolvableAnnotation._Exotic()

        def ok_plan(
            thing: TestUnresolvableAnnotation._Exotic = default_val,
        ) -> MsgGenerator[None]:
            yield  # type: ignore

        spec = create_plan_spec(ok_plan, {})
        assert spec.parameters[0].name == "thing"

    def test_var_keyword_exotic_does_not_raise(self) -> None:
        """**kwargs are never turned into widgets; no probe needed."""
        def ok_plan(**kw: TestUnresolvableAnnotation._Exotic) -> MsgGenerator[None]:
            yield  # type: ignore

        spec = create_plan_spec(ok_plan, {})
        assert spec.parameters[0].kind is ParamKind.VAR_KEYWORD

    def test_error_message_contains_plan_and_param_name(self) -> None:
        def broken(widget: TestUnresolvableAnnotation._Exotic) -> MsgGenerator[None]:
            yield  # type: ignore

        with pytest.raises(UnresolvableAnnotationError, match="broken") as exc_info:
            create_plan_spec(broken, {})

        assert "widget" in str(exc_info.value)
        assert "broken" in str(exc_info.value)


# ---------------------------------------------------------------------------
# _dispatch_annotation: table entry selection
# ---------------------------------------------------------------------------


class TestDispatchAnnotation:
    """Direct unit tests for ``_dispatch_annotation``."""

    def test_literal_dispatched(self) -> None:
        fields = _dispatch_annotation(Literal["a", "b"], ParamKind.KEYWORD_ONLY, {})
        assert fields.choices == ["a", "b"]
        assert fields.device_proto is None

    def test_device_sequence_dispatched(
        self, one_detector: dict[str, _MockDetector]
    ) -> None:
        fields = _dispatch_annotation(
            Sequence[DetectorProtocol],
            ParamKind.POSITIONAL_OR_KEYWORD,
            one_detector,
        )
        assert fields.choices == ["cam"]
        assert fields.multiselect is True
        assert fields.device_proto is DetectorProtocol

    def test_single_device_dispatched(
        self, one_motor: dict[str, MockMotorDevice]
    ) -> None:
        fields = _dispatch_annotation(
            MotorProtocol, ParamKind.POSITIONAL_OR_KEYWORD, one_motor
        )
        assert fields.choices == ["stage"]
        assert fields.multiselect is False

    def test_var_positional_device_dispatched(
        self, one_detector: dict[str, _MockDetector]
    ) -> None:
        fields = _dispatch_annotation(
            DetectorProtocol, ParamKind.VAR_POSITIONAL, one_detector
        )
        assert fields.multiselect is True
        assert fields.choices == ["cam"]

    def test_primitive_falls_through_to_empty(self) -> None:
        fields = _dispatch_annotation(int, ParamKind.POSITIONAL_OR_KEYWORD, {})
        assert fields == _FieldsFromAnnotation()

    def test_empty_registry_gives_no_choices_for_device(self) -> None:
        fields = _dispatch_annotation(
            MotorProtocol, ParamKind.POSITIONAL_OR_KEYWORD, {}
        )
        assert fields.choices is None


# ---------------------------------------------------------------------------
# collect_arguments
# ---------------------------------------------------------------------------


class TestCollectArguments:
    """Tests for ``collect_arguments``."""

    def _make_spec(self, *params: ParamDescription) -> PlanSpec:
        return PlanSpec(name="plan", docs="", parameters=list(params))

    def _param(
        self,
        name: str,
        kind: ParamKind,
        annotation: object = int,
        default: object = Parameter.empty,
    ) -> ParamDescription:
        return ParamDescription(
            name=name,
            kind=kind,
            annotation=annotation,
            default=default,
        )

    def test_positional_only(self) -> None:
        spec = self._make_spec(self._param("x", ParamKind.POSITIONAL_ONLY))
        args, kwargs = collect_arguments(spec, {"x": 42})
        assert args == (42,)
        assert kwargs == {}

    def test_positional_or_keyword(self) -> None:
        spec = self._make_spec(self._param("x", ParamKind.POSITIONAL_OR_KEYWORD))
        args, kwargs = collect_arguments(spec, {"x": 7})
        assert args == (7,)
        assert kwargs == {}

    def test_keyword_only(self) -> None:
        spec = self._make_spec(self._param("n", ParamKind.KEYWORD_ONLY))
        args, kwargs = collect_arguments(spec, {"n": 3})
        assert args == ()
        assert kwargs == {"n": 3}

    def test_var_positional_sequence_expanded(self) -> None:
        spec = self._make_spec(self._param("vals", ParamKind.VAR_POSITIONAL))
        args, kwargs = collect_arguments(spec, {"vals": [1, 2, 3]})
        assert args == (1, 2, 3)

    def test_var_positional_single_value_wrapped(self) -> None:
        spec = self._make_spec(self._param("vals", ParamKind.VAR_POSITIONAL))
        args, kwargs = collect_arguments(spec, {"vals": 99})
        assert args == (99,)

    def test_var_keyword_mapping_merged(self) -> None:
        spec = self._make_spec(self._param("kw", ParamKind.VAR_KEYWORD))
        args, kwargs = collect_arguments(spec, {"kw": {"a": 1, "b": 2}})
        assert kwargs == {"a": 1, "b": 2}

    def test_var_keyword_non_mapping_raises(self) -> None:
        spec = self._make_spec(self._param("kw", ParamKind.VAR_KEYWORD))
        with pytest.raises(TypeError, match="Mapping"):
            collect_arguments(spec, {"kw": "not_a_mapping"})

    def test_missing_param_skipped(self) -> None:
        spec = self._make_spec(
            self._param("x", ParamKind.POSITIONAL_OR_KEYWORD),
            self._param("y", ParamKind.POSITIONAL_OR_KEYWORD),
        )
        args, kwargs = collect_arguments(spec, {"x": 1})
        assert args == (1,)

    def test_ordering_preserved(self) -> None:
        spec = self._make_spec(
            self._param("a", ParamKind.POSITIONAL_OR_KEYWORD),
            self._param("b", ParamKind.POSITIONAL_OR_KEYWORD),
            self._param("c", ParamKind.POSITIONAL_OR_KEYWORD),
        )
        args, _ = collect_arguments(spec, {"a": 1, "b": 2, "c": 3})
        assert args == (1, 2, 3)


# ---------------------------------------------------------------------------
# resolve_arguments
# ---------------------------------------------------------------------------


class TestResolveArguments:
    """Tests for ``resolve_arguments``."""

    def _make_spec(self, *params: ParamDescription) -> PlanSpec:
        return PlanSpec(name="plan", docs="", parameters=list(params))

    def test_non_device_param_passed_through(self) -> None:
        spec = self._make_spec(
            ParamDescription(
                name="frames",
                kind=ParamKind.POSITIONAL_OR_KEYWORD,
                annotation=int,
                default=1,
            )
        )
        resolved = resolve_arguments(spec, {"frames": 5}, {})
        assert resolved["frames"] == 5

    def test_action_injected_when_absent(self) -> None:
        @dataclass
        class MyAction(Action):
            name: str = "go"

        action_instance = MyAction()
        spec = self._make_spec(
            ParamDescription(
                name="go",
                kind=ParamKind.POSITIONAL_ONLY,
                annotation=Action,
                default=action_instance,
                actions=action_instance,
            )
        )
        resolved = resolve_arguments(spec, {}, {})
        assert resolved["go"] is action_instance

    def test_action_not_overwritten_when_present(self) -> None:
        @dataclass
        class MyAction(Action):
            name: str = "go"

        a1 = MyAction()
        a2 = MyAction()
        spec = self._make_spec(
            ParamDescription(
                name="go",
                kind=ParamKind.POSITIONAL_ONLY,
                annotation=Action,
                default=a1,
                actions=a1,
            )
        )
        resolved = resolve_arguments(spec, {"go": a2}, {})
        assert resolved["go"] is a2

    def test_single_device_label_resolved(
        self, one_motor: dict[str, MockMotorDevice]
    ) -> None:
        spec = self._make_spec(
            ParamDescription(
                name="motor",
                kind=ParamKind.POSITIONAL_OR_KEYWORD,
                annotation=MotorProtocol,
                default=Parameter.empty,
                choices=["stage"],
                device_proto=MotorProtocol,
            )
        )
        resolved = resolve_arguments(spec, {"motor": "stage"}, one_motor)
        assert resolved["motor"] is one_motor["stage"]

    def test_device_sequence_labels_resolved(
        self, one_detector: dict[str, _MockDetector]
    ) -> None:
        spec = self._make_spec(
            ParamDescription(
                name="dets",
                kind=ParamKind.POSITIONAL_OR_KEYWORD,
                annotation=Sequence[DetectorProtocol],
                default=Parameter.empty,
                choices=["cam"],
                multiselect=True,
                device_proto=DetectorProtocol,
            )
        )
        resolved = resolve_arguments(spec, {"dets": ["cam"]}, one_detector)
        assert resolved["dets"] == [one_detector["cam"]]

    def test_unknown_label_resolves_to_none_for_single(
        self, one_motor: dict[str, MockMotorDevice]
    ) -> None:
        spec = self._make_spec(
            ParamDescription(
                name="motor",
                kind=ParamKind.POSITIONAL_OR_KEYWORD,
                annotation=MotorProtocol,
                default=Parameter.empty,
                choices=["stage"],
                device_proto=MotorProtocol,
            )
        )
        resolved = resolve_arguments(spec, {"motor": "nonexistent"}, one_motor)
        assert resolved["motor"] is None


# ---------------------------------------------------------------------------
# create_param_widget: factory registry
# ---------------------------------------------------------------------------


class TestCreateParamWidget:
    """Tests for ``create_param_widget`` — requires a Qt platform."""

    @pytest.fixture(autouse=True)
    def _require_qt(self, qapp: object) -> None:  # noqa: PT004
        """Ensure a QApplication exists; skip if no display is available."""

    def _param(
        self,
        name: str,
        annotation: object,
        kind: ParamKind = ParamKind.POSITIONAL_OR_KEYWORD,
        default: object = Parameter.empty,
        choices: list[str] | None = None,
        multiselect: bool = False,
        device_proto: object = None,
        actions: object = None,
        hidden: bool = False,
    ) -> ParamDescription:
        return ParamDescription(
            name=name,
            kind=kind,
            annotation=annotation,
            default=default,
            choices=choices,
            multiselect=multiselect,
            device_proto=device_proto,
            actions=actions,
            hidden=hidden,
        )

    def test_int_creates_spinbox(self) -> None:
        from magicgui import widgets as mgw

        w = create_param_widget(self._param("n", int))
        assert isinstance(w, mgw.SpinBox)

    def test_float_creates_float_spinbox(self) -> None:
        from magicgui import widgets as mgw

        w = create_param_widget(self._param("x", float))
        assert isinstance(w, mgw.FloatSpinBox)

    def test_bool_creates_checkbox(self) -> None:
        from magicgui import widgets as mgw

        w = create_param_widget(self._param("flag", bool, default=False))
        assert isinstance(w, mgw.CheckBox)

    def test_literal_creates_combobox(self) -> None:
        from magicgui import widgets as mgw

        p = self._param("egu", Literal["um", "mm"], choices=["um", "mm"])
        w = create_param_widget(p)
        assert isinstance(w, mgw.ComboBox)

    def test_single_device_creates_combobox(self) -> None:
        from magicgui import widgets as mgw

        p = self._param(
            "motor",
            MotorProtocol,
            choices=["stage"],
            device_proto=MotorProtocol,
        )
        w = create_param_widget(p)
        assert isinstance(w, mgw.ComboBox)

    def test_multiselect_device_creates_select(self) -> None:
        from magicgui import widgets as mgw

        p = self._param(
            "dets",
            Sequence[DetectorProtocol],
            choices=["cam"],
            multiselect=True,
            device_proto=DetectorProtocol,
        )
        w = create_param_widget(p)
        assert isinstance(w, mgw.Select)

    def test_path_creates_file_edit(self) -> None:
        from magicgui import widgets as mgw

        w = create_param_widget(self._param("output", Path))
        assert isinstance(w, mgw.FileEdit)

    def test_sequence_int_creates_list_edit(self) -> None:
        from magicgui import widgets as mgw

        w = create_param_widget(self._param("vals", Sequence[int]))
        assert isinstance(w, mgw.ListEdit)

    def test_hidden_param_creates_line_edit_placeholder(self) -> None:
        from magicgui import widgets as mgw

        p = self._param("secret", int, hidden=True)
        w = create_param_widget(p)
        assert isinstance(w, mgw.LineEdit)

    def test_action_param_creates_line_edit_placeholder(self) -> None:
        from magicgui import widgets as mgw

        @dataclass
        class Snap(Action):
            name: str = "snap"

        snap = Snap()
        p = self._param("snap", Action, actions=snap)
        w = create_param_widget(p)
        assert isinstance(w, mgw.LineEdit)

    def test_unresolvable_annotation_raises_not_lineedit(self) -> None:
        """create_param_widget raises RuntimeError for truly exotic annotations.

        This should never happen in normal operation (create_plan_spec guards
        against it), but we verify the contract here explicitly.
        """

        class Exotic:
            pass

        p = self._param("thing", Exotic)
        with pytest.raises((TypeError, ValueError, RuntimeError)):
            create_param_widget(p)
