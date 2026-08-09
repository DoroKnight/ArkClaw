"""Contract tests for the isolated Spine 3.8 ctypes catalog binding."""

from __future__ import annotations

import ctypes
import gc
import importlib
import inspect
import math
import threading
import traceback
import weakref
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import Any, NoReturn, cast

import pytest

from sjtuclaw.application.pet_external_assets import ExternalPetAssetSnapshot


class FakeFunction:
    """A Python callable that records the ctypes ABI declaration applied to it."""

    def __init__(self, callback: Callable[..., object]) -> None:
        self._callback = callback
        self.argtypes: list[object] | None = None
        self.restype: object | None = None

    def __call__(self, *args: object) -> object:
        return self._callback(*args)


class FakeVertex(ctypes.Structure):
    _fields_ = [
        ("x", ctypes.c_float),
        ("y", ctypes.c_float),
        ("u", ctypes.c_float),
        ("v", ctypes.c_float),
        ("r", ctypes.c_uint8),
        ("g", ctypes.c_uint8),
        ("b", ctypes.c_uint8),
        ("a", ctypes.c_uint8),
    ]


class FakeDrawView(ctypes.Structure):
    _fields_ = [
        ("vertices", ctypes.POINTER(FakeVertex)),
        ("vertex_count", ctypes.c_size_t),
        ("indices", ctypes.POINTER(ctypes.c_uint32)),
        ("index_count", ctypes.c_size_t),
        ("texture_page", ctypes.c_uint32),
        ("blend_mode", ctypes.c_uint32),
        ("draw_order", ctypes.c_int32),
    ]


class FakeEventView(ctypes.Structure):
    _fields_ = [
        ("event_type", ctypes.c_uint32),
        ("track", ctypes.c_uint32),
        ("loop_ordinal", ctypes.c_uint64),
        ("animation_name_utf8", ctypes.POINTER(ctypes.c_char)),
        ("animation_name_size", ctypes.c_size_t),
    ]


class FakeLibrary:
    """In-process ABI fake; it replaces only the external DLL boundary."""

    def __init__(self) -> None:
        self.abi_version = 1
        self.create_code = 0
        self.animation_info_code = 0
        self.skin_info_code = 0
        self.bounds_code = 0
        self.set_animation_code = 0
        self.update_code = 0
        self.draw_view_code = 0
        self.animations = (("idle-猫", 1.25),)
        self.skins = ("default",)
        self.animation_count_override: object | None = None
        self.skin_count_override: object | None = None
        self.animation_capacity_override: object | None = None
        self.skin_capacity_override: object | None = None
        self.animation_name_bytes_override: bytes | None = None
        self.skin_name_bytes_override: bytes | None = None
        self.bounds = (-2.0, 3.0, 4.0, 5.0)
        self.set_animation_calls: list[tuple[int, bytes, int]] = []
        self.update_calls: list[float] = []
        self.clear_track_calls: list[int] = []
        self.events: list[tuple[int, int, int, bytes]] = []
        self._event_name_buffers: list[object] = []
        self.draw_count_override: object | None = None
        self.draw_vertex_count_override: object | None = None
        self.draw_index_count_override: object | None = None
        self.draw_texture_page = 0
        self.draw_blend_mode = 2
        self.draw_order = 7
        self.draw_vertices = (FakeVertex * 3)(
            FakeVertex(1.0, 2.0, 0.0, 0.0, 10, 20, 30, 40),
            FakeVertex(3.0, 4.0, 1.0, 0.0, 50, 60, 70, 80),
            FakeVertex(5.0, 6.0, 0.0, 1.0, 90, 100, 110, 120),
        )
        self.draw_indices = (ctypes.c_uint32 * 3)(0, 1, 2)
        self.destroy_count = 0
        self.animation_info_calls = 0
        self.skin_info_calls = 0
        self.reject_animation_name_size_call = False
        self.reject_skin_name_size_call = False
        self.native_calls_after_destroy = 0
        self.destroyed = threading.Event()
        self.animation_count_started: threading.Event | None = None
        self.animation_count_release: threading.Event | None = None
        self.create_inputs: tuple[bytes, bytes] | None = None
        self.sjtuclaw_spine38_abi_version = FakeFunction(self._abi_version)
        self.sjtuclaw_spine38_create = FakeFunction(self._create)
        self.sjtuclaw_spine38_destroy = FakeFunction(self._destroy)
        self.sjtuclaw_spine38_animation_count = FakeFunction(self._animation_count)
        self.sjtuclaw_spine38_animation_name_size = FakeFunction(
            self._animation_name_size
        )
        self.sjtuclaw_spine38_animation_info = FakeFunction(self._animation_info)
        self.sjtuclaw_spine38_skin_count = FakeFunction(self._skin_count)
        self.sjtuclaw_spine38_skin_name_size = FakeFunction(self._skin_name_size)
        self.sjtuclaw_spine38_skin_info = FakeFunction(self._skin_info)
        self.sjtuclaw_spine38_setup_bounds = FakeFunction(self._setup_bounds)
        self.sjtuclaw_spine38_set_animation = FakeFunction(self._set_animation)
        self.sjtuclaw_spine38_update = FakeFunction(self._update)
        self.sjtuclaw_spine38_clear_track = FakeFunction(self._clear_track)
        self.sjtuclaw_spine38_event_count = FakeFunction(self._event_count)
        self.sjtuclaw_spine38_event_view = FakeFunction(self._event_view)
        self.sjtuclaw_spine38_draw_count = FakeFunction(self._draw_count)
        self.sjtuclaw_spine38_draw_view = FakeFunction(self._draw_view)

    def _abi_version(self) -> int:
        return self.abi_version

    def _create(
        self,
        skeleton: object,
        skeleton_size: object,
        atlas: object,
        atlas_size: object,
        out_handle: object,
    ) -> int:
        self.create_inputs = (
            ctypes.string_at(cast(Any, skeleton), cast(Any, skeleton_size)),
            ctypes.string_at(cast(Any, atlas), cast(Any, atlas_size)),
        )
        if self.create_code == 0:
            ctypes.cast(cast(Any, out_handle), ctypes.POINTER(ctypes.c_void_p))[0] = (
                ctypes.c_void_p(101)
            )
        return self.create_code

    def _destroy(self, handle: object) -> None:
        assert ctypes.cast(cast(Any, handle), ctypes.c_void_p).value == 101
        self.destroy_count += 1
        self.destroyed.set()

    def _animation_count(self, handle: object) -> object:
        self._assert_handle(handle)
        if self.animation_count_started is not None:
            self.animation_count_started.set()
            assert self.animation_count_release is not None
            assert self.animation_count_release.wait(timeout=5)
        if self.animation_count_override is not None:
            return self.animation_count_override
        return len(self.animations)

    def _animation_name_size(self, handle: object, index: object) -> object:
        self._assert_handle(handle)
        if self.reject_animation_name_size_call:
            raise AssertionError("animation count was not rejected before iteration")
        if self.animation_capacity_override is not None:
            return self.animation_capacity_override
        name, _ = self.animations[cast(int, index) % len(self.animations)]
        return len(name.encode("utf-8")) + 1

    def _animation_info(
        self,
        handle: object,
        index: object,
        name: object,
        capacity: object,
        duration: object,
    ) -> int:
        self._assert_handle(handle)
        self.animation_info_calls += 1
        if self.animation_info_code != 0:
            return self.animation_info_code
        animation_name, value = self.animations[cast(int, index) % len(self.animations)]
        encoded = self.animation_name_bytes_override
        if encoded is None:
            encoded = animation_name.encode("utf-8") + b"\0"
        assert len(encoded) <= cast(int, capacity)
        ctypes.memmove(cast(Any, name), encoded, len(encoded))
        ctypes.cast(cast(Any, duration), ctypes.POINTER(ctypes.c_float))[0] = value
        return 0

    def _skin_count(self, handle: object) -> object:
        self._assert_handle(handle)
        if self.skin_count_override is not None:
            return self.skin_count_override
        return len(self.skins)

    def _skin_name_size(self, handle: object, index: object) -> object:
        self._assert_handle(handle)
        if self.reject_skin_name_size_call:
            raise AssertionError("skin count was not rejected before iteration")
        if self.skin_capacity_override is not None:
            return self.skin_capacity_override
        return len(self.skins[cast(int, index) % len(self.skins)].encode("utf-8")) + 1

    def _skin_info(
        self,
        handle: object,
        index: object,
        name: object,
        capacity: object,
    ) -> int:
        self._assert_handle(handle)
        self.skin_info_calls += 1
        if self.skin_info_code != 0:
            return self.skin_info_code
        encoded = self.skin_name_bytes_override
        if encoded is None:
            encoded = self.skins[cast(int, index) % len(self.skins)].encode("utf-8") + b"\0"
        assert len(encoded) <= cast(int, capacity)
        ctypes.memmove(cast(Any, name), encoded, len(encoded))
        return 0

    def _setup_bounds(self, handle: object, bounds: object) -> int:
        self._assert_handle(handle)
        if self.bounds_code != 0:
            return self.bounds_code
        output = ctypes.cast(cast(Any, bounds), ctypes.POINTER(FakeBounds))[0]
        output.x, output.y, output.width, output.height = self.bounds
        return 0

    def _set_animation(
        self,
        handle: object,
        track: object,
        name: object,
        name_size: object,
        loop: object,
    ) -> int:
        self._assert_handle(handle)
        self.set_animation_calls.append(
            (
                cast(int, track),
                ctypes.string_at(cast(Any, name), cast(Any, name_size)),
                cast(int, loop),
            )
        )
        return self.set_animation_code

    def _update(self, handle: object, delta_seconds: object) -> int:
        self._assert_handle(handle)
        self.update_calls.append(float(cast(float, delta_seconds)))
        return self.update_code

    def _clear_track(self, handle: object, track: object) -> int:
        self._assert_handle(handle)
        self.clear_track_calls.append(cast(int, track))
        self.events.clear()
        return 0

    def _event_count(self, handle: object) -> int:
        self._assert_handle(handle)
        return len(self.events)

    def _event_view(
        self,
        handle: object,
        index: object,
        view: object,
        capacity: object,
    ) -> int:
        self._assert_handle(handle)
        assert cast(int, capacity) >= ctypes.sizeof(FakeEventView)
        event_type, track, ordinal, name = self.events[cast(int, index)]
        name_buffer = (ctypes.c_char * len(name)).from_buffer_copy(name)
        self._event_name_buffers.append(name_buffer)
        output = ctypes.cast(cast(Any, view), ctypes.POINTER(FakeEventView))[0]
        output.event_type = event_type
        output.track = track
        output.loop_ordinal = ordinal
        output.animation_name_utf8 = ctypes.cast(
            name_buffer,
            ctypes.POINTER(ctypes.c_char),
        )
        output.animation_name_size = len(name)
        return 0

    def _draw_count(self, handle: object) -> object:
        self._assert_handle(handle)
        if self.draw_count_override is not None:
            return self.draw_count_override
        return 1

    def _draw_view(
        self,
        handle: object,
        index: object,
        out_view: object,
        view_capacity: object,
    ) -> int:
        self._assert_handle(handle)
        assert cast(int, index) == 0
        assert cast(int, view_capacity) == ctypes.sizeof(FakeDrawView)
        if self.draw_view_code != 0:
            return self.draw_view_code
        output = ctypes.cast(cast(Any, out_view), ctypes.POINTER(FakeDrawView))[0]
        output.vertices = ctypes.cast(
            self.draw_vertices, ctypes.POINTER(FakeVertex)
        )
        output.vertex_count = (
            len(self.draw_vertices)
            if self.draw_vertex_count_override is None
            else cast(int, self.draw_vertex_count_override)
        )
        output.indices = ctypes.cast(
            self.draw_indices, ctypes.POINTER(ctypes.c_uint32)
        )
        output.index_count = (
            len(self.draw_indices)
            if self.draw_index_count_override is None
            else cast(int, self.draw_index_count_override)
        )
        output.texture_page = self.draw_texture_page
        output.blend_mode = self.draw_blend_mode
        output.draw_order = self.draw_order
        return 0

    def _assert_handle(self, handle: object) -> None:
        assert ctypes.cast(cast(Any, handle), ctypes.c_void_p).value == 101
        if self.destroyed.is_set():
            self.native_calls_after_destroy += 1


class _ExplodingInteger:
    def __init__(self, error_type: type[MemoryError] | type[OverflowError]) -> None:
        self._error_type = error_type

    def __int__(self) -> int:
        raise self._error_type("sensitive-native-size")


class _TwoThreadFalseGate:
    """Makes the pre-lock implementation's two close checks overlap."""

    def __init__(self) -> None:
        self._barrier = threading.Barrier(2)

    def __bool__(self) -> bool:
        with suppress(threading.BrokenBarrierError):
            self._barrier.wait(timeout=0.2)
        return False


class FakeBounds(ctypes.Structure):
    _fields_ = [
        ("x", ctypes.c_float),
        ("y", ctypes.c_float),
        ("width", ctypes.c_float),
        ("height", ctypes.c_float),
    ]


@pytest.fixture
def fake_library() -> FakeLibrary:
    return FakeLibrary()


@pytest.fixture
def snapshot() -> ExternalPetAssetSnapshot:
    return ExternalPetAssetSnapshot(
        skeleton_bytes=b"skeleton-bytes",
        atlas_bytes=b"page.png\nsize: 1,1\n",
        texture_bytes=b"texture-not-used-by-the-bridge",
    )


def _snapshot_with_skeleton_size(size: int) -> ExternalPetAssetSnapshot:
    return ExternalPetAssetSnapshot(
        skeleton_bytes=b"s" * size,
        atlas_bytes=b"page.png\nsize: 1,1\n",
        texture_bytes=b"texture-not-used-by-the-bridge",
    )


def test_native_binding_rejects_wrong_abi(fake_library: FakeLibrary) -> None:
    native = importlib.import_module("sjtuclaw.infrastructure.spine38_native")
    fake_library.abi_version = 2

    with pytest.raises(native.Spine38NativeError) as caught:
        native.Spine38NativeLibrary(fake_library)

    assert caught.value.code is native.Spine38NativeCode.ABI_MISMATCH


def test_native_binding_rejects_library_missing_a_bridge_symbol(
    fake_library: FakeLibrary,
) -> None:
    native = importlib.import_module("sjtuclaw.infrastructure.spine38_native")
    del fake_library.sjtuclaw_spine38_setup_bounds

    with pytest.raises(native.Spine38NativeError) as caught:
        native.Spine38NativeLibrary(fake_library)

    assert caught.value.code is native.Spine38NativeCode.ABI_MISMATCH


def test_native_binding_declares_every_catalog_abi_signature(
    fake_library: FakeLibrary,
) -> None:
    native = importlib.import_module("sjtuclaw.infrastructure.spine38_native")

    native.Spine38NativeLibrary(fake_library)

    assert fake_library.sjtuclaw_spine38_abi_version.argtypes == []
    assert fake_library.sjtuclaw_spine38_abi_version.restype is ctypes.c_uint32
    assert fake_library.sjtuclaw_spine38_create.argtypes == [
        ctypes.POINTER(ctypes.c_uint8),
        ctypes.c_size_t,
        ctypes.POINTER(ctypes.c_char),
        ctypes.c_size_t,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    assert fake_library.sjtuclaw_spine38_create.restype is ctypes.c_int
    assert fake_library.sjtuclaw_spine38_destroy.argtypes == [ctypes.c_void_p]
    assert fake_library.sjtuclaw_spine38_destroy.restype is None
    assert fake_library.sjtuclaw_spine38_animation_count.argtypes == [ctypes.c_void_p]
    assert fake_library.sjtuclaw_spine38_animation_count.restype is ctypes.c_size_t
    assert fake_library.sjtuclaw_spine38_animation_name_size.argtypes == [
        ctypes.c_void_p,
        ctypes.c_size_t,
    ]
    assert fake_library.sjtuclaw_spine38_animation_name_size.restype is ctypes.c_size_t
    assert fake_library.sjtuclaw_spine38_animation_info.argtypes == [
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.POINTER(ctypes.c_char),
        ctypes.c_size_t,
        ctypes.POINTER(ctypes.c_float),
    ]
    assert fake_library.sjtuclaw_spine38_animation_info.restype is ctypes.c_int
    assert fake_library.sjtuclaw_spine38_skin_count.argtypes == [ctypes.c_void_p]
    assert fake_library.sjtuclaw_spine38_skin_count.restype is ctypes.c_size_t
    assert fake_library.sjtuclaw_spine38_skin_name_size.argtypes == [
        ctypes.c_void_p,
        ctypes.c_size_t,
    ]
    assert fake_library.sjtuclaw_spine38_skin_name_size.restype is ctypes.c_size_t
    assert fake_library.sjtuclaw_spine38_skin_info.argtypes == [
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.POINTER(ctypes.c_char),
        ctypes.c_size_t,
    ]
    assert fake_library.sjtuclaw_spine38_skin_info.restype is ctypes.c_int
    assert fake_library.sjtuclaw_spine38_setup_bounds.argtypes == [
        ctypes.c_void_p,
        ctypes.POINTER(native._SjtuclawSpine38Bounds),
    ]
    assert fake_library.sjtuclaw_spine38_setup_bounds.restype is ctypes.c_int
    assert fake_library.sjtuclaw_spine38_set_animation.argtypes == [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_char),
        ctypes.c_size_t,
        ctypes.c_uint8,
    ]
    assert fake_library.sjtuclaw_spine38_set_animation.restype is ctypes.c_int
    assert fake_library.sjtuclaw_spine38_update.argtypes == [
        ctypes.c_void_p,
        ctypes.c_float,
    ]
    assert fake_library.sjtuclaw_spine38_update.restype is ctypes.c_int
    assert fake_library.sjtuclaw_spine38_clear_track.argtypes == [
        ctypes.c_void_p,
        ctypes.c_uint32,
    ]
    assert fake_library.sjtuclaw_spine38_clear_track.restype is ctypes.c_int
    assert fake_library.sjtuclaw_spine38_event_count.argtypes == [ctypes.c_void_p]
    assert fake_library.sjtuclaw_spine38_event_count.restype is ctypes.c_size_t
    assert fake_library.sjtuclaw_spine38_event_view.argtypes == [
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.POINTER(native._SjtuclawSpine38EventView),
        ctypes.c_size_t,
    ]
    assert fake_library.sjtuclaw_spine38_event_view.restype is ctypes.c_int
    assert fake_library.sjtuclaw_spine38_draw_count.argtypes == [ctypes.c_void_p]
    assert fake_library.sjtuclaw_spine38_draw_count.restype is ctypes.c_size_t
    assert fake_library.sjtuclaw_spine38_draw_view.argtypes == [
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.POINTER(native._SjtuclawSpine38DrawView),
        ctypes.c_size_t,
    ]
    assert fake_library.sjtuclaw_spine38_draw_view.restype is ctypes.c_int


def test_native_binding_copies_catalog_strings_and_validates_values(
    fake_library: FakeLibrary,
    snapshot: ExternalPetAssetSnapshot,
) -> None:
    native = importlib.import_module("sjtuclaw.infrastructure.spine38_native")
    port = native.Spine38NativeLibrary(fake_library).create(snapshot)

    assert fake_library.create_inputs == (snapshot.skeleton_bytes, snapshot.atlas_bytes)
    assert port.catalog() == (native.Spine38AnimationInfo("idle-猫", 1.25),)
    assert port.skins() == ("default",)
    assert port.setup_bounds() == native.Spine38Bounds(-2.0, 3.0, 4.0, 5.0)
    with pytest.raises(AttributeError):
        port.catalog()[0].name = "changed"


def test_native_binding_controls_playback_and_copies_draw_views_immediately(
    fake_library: FakeLibrary,
    snapshot: ExternalPetAssetSnapshot,
) -> None:
    native = importlib.import_module("sjtuclaw.infrastructure.spine38_native")
    port = native.Spine38NativeLibrary(fake_library).create(snapshot)

    port.set_animation(0, "idle-猫", True)
    port.update(0.25)
    commands = port.draw_commands()

    assert fake_library.set_animation_calls == [(0, "idle-猫".encode(), 1)]
    assert fake_library.update_calls == [0.25]
    assert commands == (
        native.Spine38DrawCommand(
            vertices=(
                native.Spine38Vertex(1.0, 2.0, 0.0, 0.0, 10, 20, 30, 40),
                native.Spine38Vertex(3.0, 4.0, 1.0, 0.0, 50, 60, 70, 80),
                native.Spine38Vertex(5.0, 6.0, 0.0, 1.0, 90, 100, 110, 120),
            ),
            indices=(0, 1, 2),
            texture_page=0,
            blend_mode=native.Spine38BlendMode.MULTIPLY,
            draw_order=7,
        ),
    )
    fake_library.draw_vertices[0].x = 999.0
    fake_library.draw_indices[0] = 2
    assert commands[0].vertices[0].x == 1.0
    assert commands[0].indices == (0, 1, 2)


def test_native_binding_copies_playback_events_before_native_mutation(
    fake_library: FakeLibrary,
    snapshot: ExternalPetAssetSnapshot,
) -> None:
    native = importlib.import_module("sjtuclaw.infrastructure.spine38_native")
    fake_library.events = [(2, 0, 3, b"Move")]
    port = native.Spine38NativeLibrary(fake_library).create(snapshot)

    events = port.playback_events()
    fake_library.events = [(1, 0, 0, b"Relax")]
    fake_library._event_name_buffers.clear()

    assert events == (
        native.Spine38NativePlaybackEvent(
            native.Spine38NativeEventType.LOOP_BOUNDARY,
            "Move",
            3,
        ),
    )
    port.clear_track(0)
    assert fake_library.clear_track_calls == [0]


@pytest.mark.parametrize(
    ("track", "name", "loop"),
    [
        (-1, "idle", True),
        (256, "idle", True),
        (0, "", True),
        (0, "bad\0name", True),
        (0, "idle", 1),
    ],
)
def test_native_binding_rejects_invalid_playback_arguments_before_native_call(
    fake_library: FakeLibrary,
    snapshot: ExternalPetAssetSnapshot,
    track: int,
    name: str,
    loop: object,
) -> None:
    native = importlib.import_module("sjtuclaw.infrastructure.spine38_native")
    port = native.Spine38NativeLibrary(fake_library).create(snapshot)

    with pytest.raises(native.Spine38NativeError) as caught:
        port.set_animation(track, name, loop)

    assert caught.value.code is native.Spine38NativeCode.INVALID_ARGUMENT
    assert fake_library.set_animation_calls == []


@pytest.mark.parametrize("delta", [-0.01, math.nan, math.inf, True])
def test_native_binding_rejects_invalid_update_before_native_call(
    fake_library: FakeLibrary,
    snapshot: ExternalPetAssetSnapshot,
    delta: object,
) -> None:
    native = importlib.import_module("sjtuclaw.infrastructure.spine38_native")
    port = native.Spine38NativeLibrary(fake_library).create(snapshot)

    with pytest.raises(native.Spine38NativeError) as caught:
        port.update(delta)

    assert caught.value.code is native.Spine38NativeCode.INVALID_ARGUMENT
    assert fake_library.update_calls == []


@pytest.mark.parametrize(
    ("attribute", "value"),
    [
        ("draw_count_override", 4097),
        ("draw_vertex_count_override", 4097),
        ("draw_index_count_override", 4097),
        ("draw_texture_page", 1),
        ("draw_blend_mode", 4),
        ("draw_order", -1),
    ],
)
def test_native_binding_rejects_invalid_or_unbounded_draw_views(
    fake_library: FakeLibrary,
    snapshot: ExternalPetAssetSnapshot,
    attribute: str,
    value: int,
) -> None:
    native = importlib.import_module("sjtuclaw.infrastructure.spine38_native")
    setattr(fake_library, attribute, value)
    port = native.Spine38NativeLibrary(fake_library).create(
        _snapshot_with_skeleton_size(4097)
    )

    with pytest.raises(native.Spine38NativeError) as caught:
        port.draw_commands()

    assert caught.value.code is native.Spine38NativeCode.RUNTIME_FAILURE


def test_native_binding_rejects_out_of_range_native_draw_index(
    fake_library: FakeLibrary,
    snapshot: ExternalPetAssetSnapshot,
) -> None:
    native = importlib.import_module("sjtuclaw.infrastructure.spine38_native")
    fake_library.draw_indices[2] = 3
    port = native.Spine38NativeLibrary(fake_library).create(snapshot)

    with pytest.raises(native.Spine38NativeError) as caught:
        port.draw_commands()

    assert caught.value.code is native.Spine38NativeCode.RUNTIME_FAILURE


@pytest.mark.parametrize("path", ["bridge.dll", Path("relative/bridge.dll")])
def test_native_binding_rejects_non_absolute_dll_paths(path: str | Path) -> None:
    native = importlib.import_module("sjtuclaw.infrastructure.spine38_native")

    with pytest.raises(native.Spine38NativeError) as caught:
        native.Spine38NativeLibrary.from_dll_path(path)

    assert caught.value.code is native.Spine38NativeCode.DLL_PATH_INVALID


def test_native_binding_rejects_missing_dll_path(tmp_path: Path) -> None:
    native = importlib.import_module("sjtuclaw.infrastructure.spine38_native")

    with pytest.raises(native.Spine38NativeError) as caught:
        native.Spine38NativeLibrary.from_dll_path(tmp_path / "missing.dll")

    assert caught.value.code is native.Spine38NativeCode.DLL_PATH_INVALID


def test_native_binding_discards_dll_loader_diagnostics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    native = importlib.import_module("sjtuclaw.infrastructure.spine38_native")
    dll_path = tmp_path / "sentinel-private-path.dll"
    dll_path.write_bytes(b"not-a-dll")

    def fail_load(path: str) -> NoReturn:
        raise OSError(f"native loader exposed {path}")

    monkeypatch.setattr(native.ctypes, "CDLL", fail_load)

    with pytest.raises(native.Spine38NativeError) as caught:
        native.Spine38NativeLibrary.from_dll_path(dll_path)

    assert caught.value.code is native.Spine38NativeCode.DLL_PATH_INVALID
    rendered = "".join(traceback.format_exception(caught.value))
    assert "sentinel-private-path" not in rendered
    assert caught.value.__cause__ is None


@pytest.mark.parametrize("native_code", [2, 6, 999])
def test_native_binding_never_leaks_unknown_native_codes(
    fake_library: FakeLibrary,
    snapshot: ExternalPetAssetSnapshot,
    native_code: int,
) -> None:
    native = importlib.import_module("sjtuclaw.infrastructure.spine38_native")
    fake_library.create_code = native_code

    with pytest.raises(native.Spine38NativeError) as caught:
        native.Spine38NativeLibrary(fake_library).create(snapshot)

    expected = (
        native.Spine38NativeCode.ATLAS_LOAD_FAILED
        if native_code == 2
        else native.Spine38NativeCode.RUNTIME_FAILURE
    )
    assert caught.value.code is expected


@pytest.mark.parametrize(
    ("duration", "bounds"),
    [
        (0.0, (-2.0, 3.0, 4.0, 5.0)),
        (math.inf, (-2.0, 3.0, 4.0, 5.0)),
        (1.25, (-2.0, 3.0, 0.0, 5.0)),
        (1.25, (-2.0, 3.0, 4.0, math.nan)),
    ],
)
def test_native_binding_rejects_invalid_catalog_values(
    fake_library: FakeLibrary,
    snapshot: ExternalPetAssetSnapshot,
    duration: float,
    bounds: tuple[float, float, float, float],
) -> None:
    native = importlib.import_module("sjtuclaw.infrastructure.spine38_native")
    fake_library.animations = (("idle", duration),)
    fake_library.bounds = bounds
    port = native.Spine38NativeLibrary(fake_library).create(snapshot)

    with pytest.raises(native.Spine38NativeError) as caught:
        if duration <= 0 or not math.isfinite(duration):
            port.catalog()
        else:
            port.setup_bounds()

    assert caught.value.code is native.Spine38NativeCode.RUNTIME_FAILURE


@pytest.mark.parametrize(
    ("method_name", "count_attribute"),
    [("catalog", "animation_count_override"), ("skins", "skin_count_override")],
)
def test_native_binding_accepts_zero_catalog_counts(
    fake_library: FakeLibrary,
    snapshot: ExternalPetAssetSnapshot,
    method_name: str,
    count_attribute: str,
) -> None:
    native = importlib.import_module("sjtuclaw.infrastructure.spine38_native")
    setattr(fake_library, count_attribute, 0)
    port = native.Spine38NativeLibrary(fake_library).create(snapshot)

    assert getattr(port, method_name)() == ()


@pytest.mark.parametrize(
    ("method_name", "count_attribute"),
    [("catalog", "animation_count_override"), ("skins", "skin_count_override")],
)
def test_native_binding_accepts_catalog_count_at_policy_boundary(
    fake_library: FakeLibrary,
    method_name: str,
    count_attribute: str,
) -> None:
    native = importlib.import_module("sjtuclaw.infrastructure.spine38_native")
    setattr(fake_library, count_attribute, 4096)
    port = native.Spine38NativeLibrary(fake_library).create(
        _snapshot_with_skeleton_size(4096)
    )

    assert len(getattr(port, method_name)()) == 4096


@pytest.mark.parametrize(
    ("method_name", "count_attribute", "reject_size_call_attribute"),
    [
        ("catalog", "animation_count_override", "reject_animation_name_size_call"),
        ("skins", "skin_count_override", "reject_skin_name_size_call"),
    ],
)
@pytest.mark.parametrize("count", [-1, 4097, ctypes.c_size_t(-1).value])
def test_native_binding_rejects_invalid_or_excessive_catalog_counts_before_iteration(
    fake_library: FakeLibrary,
    method_name: str,
    count_attribute: str,
    reject_size_call_attribute: str,
    count: int,
) -> None:
    native = importlib.import_module("sjtuclaw.infrastructure.spine38_native")
    setattr(fake_library, count_attribute, count)
    setattr(fake_library, reject_size_call_attribute, True)
    port = native.Spine38NativeLibrary(fake_library).create(
        _snapshot_with_skeleton_size(4097)
    )

    with pytest.raises(native.Spine38NativeError) as caught:
        getattr(port, method_name)()

    assert caught.value.code is native.Spine38NativeCode.RUNTIME_FAILURE


@pytest.mark.parametrize(
    ("method_name", "count_attribute"),
    [("catalog", "animation_count_override"), ("skins", "skin_count_override")],
)
def test_native_binding_bounds_catalog_count_by_verified_skeleton_size(
    fake_library: FakeLibrary,
    method_name: str,
    count_attribute: str,
) -> None:
    native = importlib.import_module("sjtuclaw.infrastructure.spine38_native")
    setattr(fake_library, count_attribute, 9)
    port = native.Spine38NativeLibrary(fake_library).create(
        _snapshot_with_skeleton_size(8)
    )

    with pytest.raises(native.Spine38NativeError) as caught:
        getattr(port, method_name)()

    assert caught.value.code is native.Spine38NativeCode.RUNTIME_FAILURE


@pytest.mark.parametrize(
    ("method_name", "capacity_attribute", "payload_attribute"),
    [
        ("catalog", "animation_capacity_override", "animation_name_bytes_override"),
        ("skins", "skin_capacity_override", "skin_name_bytes_override"),
    ],
)
@pytest.mark.parametrize("capacity", [2, 4096])
def test_native_binding_accepts_name_capacity_at_safe_boundaries(
    fake_library: FakeLibrary,
    method_name: str,
    capacity_attribute: str,
    payload_attribute: str,
    capacity: int,
) -> None:
    native = importlib.import_module("sjtuclaw.infrastructure.spine38_native")
    setattr(fake_library, capacity_attribute, capacity)
    setattr(fake_library, payload_attribute, b"a" * (capacity - 1) + b"\0")
    port = native.Spine38NativeLibrary(fake_library).create(
        _snapshot_with_skeleton_size(4096)
    )

    result = getattr(port, method_name)()

    value = result[0].name if method_name == "catalog" else result[0]
    assert value == "a" * (capacity - 1)


@pytest.mark.parametrize(
    ("method_name", "capacity_attribute", "info_calls_attribute"),
    [
        ("catalog", "animation_capacity_override", "animation_info_calls"),
        ("skins", "skin_capacity_override", "skin_info_calls"),
    ],
)
@pytest.mark.parametrize("capacity", [-1, 0, 1, 4097, ctypes.c_size_t(-1).value])
def test_native_binding_rejects_invalid_or_excessive_name_capacities_before_allocation(
    fake_library: FakeLibrary,
    method_name: str,
    capacity_attribute: str,
    info_calls_attribute: str,
    capacity: int,
) -> None:
    native = importlib.import_module("sjtuclaw.infrastructure.spine38_native")
    setattr(fake_library, capacity_attribute, capacity)
    port = native.Spine38NativeLibrary(fake_library).create(
        _snapshot_with_skeleton_size(4097)
    )

    with pytest.raises(native.Spine38NativeError) as caught:
        getattr(port, method_name)()

    assert caught.value.code is native.Spine38NativeCode.RUNTIME_FAILURE
    assert caught.value.__cause__ is None
    assert getattr(fake_library, info_calls_attribute) == 0


@pytest.mark.parametrize(
    ("method_name", "capacity_attribute"),
    [
        ("catalog", "animation_capacity_override"),
        ("skins", "skin_capacity_override"),
    ],
)
def test_native_binding_bounds_name_capacity_by_verified_skeleton_size(
    fake_library: FakeLibrary,
    method_name: str,
    capacity_attribute: str,
) -> None:
    native = importlib.import_module("sjtuclaw.infrastructure.spine38_native")
    setattr(fake_library, capacity_attribute, 9)
    port = native.Spine38NativeLibrary(fake_library).create(
        _snapshot_with_skeleton_size(8)
    )

    with pytest.raises(native.Spine38NativeError) as caught:
        getattr(port, method_name)()

    assert caught.value.code is native.Spine38NativeCode.RUNTIME_FAILURE


@pytest.mark.parametrize(
    ("method_name", "capacity_attribute"),
    [
        ("catalog", "animation_capacity_override"),
        ("skins", "skin_capacity_override"),
    ],
)
@pytest.mark.parametrize("error_type", [MemoryError, OverflowError])
def test_native_binding_normalizes_native_size_conversion_failures(
    fake_library: FakeLibrary,
    snapshot: ExternalPetAssetSnapshot,
    method_name: str,
    capacity_attribute: str,
    error_type: type[MemoryError] | type[OverflowError],
) -> None:
    native = importlib.import_module("sjtuclaw.infrastructure.spine38_native")
    setattr(fake_library, capacity_attribute, _ExplodingInteger(error_type))
    port = native.Spine38NativeLibrary(fake_library).create(snapshot)

    with pytest.raises(native.Spine38NativeError) as caught:
        getattr(port, method_name)()

    assert caught.value.code is native.Spine38NativeCode.RUNTIME_FAILURE
    assert caught.value.__cause__ is None


@pytest.mark.parametrize("error_type", [MemoryError, OverflowError])
def test_native_binding_normalizes_name_buffer_allocation_failures(
    fake_library: FakeLibrary,
    snapshot: ExternalPetAssetSnapshot,
    monkeypatch: pytest.MonkeyPatch,
    error_type: type[MemoryError] | type[OverflowError],
) -> None:
    native = importlib.import_module("sjtuclaw.infrastructure.spine38_native")

    def fail_buffer_fill(*args: object) -> NoReturn:
        raise error_type("sensitive-allocation-detail")

    monkeypatch.setattr(native.ctypes, "memset", fail_buffer_fill)
    port = native.Spine38NativeLibrary(fake_library).create(snapshot)

    with pytest.raises(native.Spine38NativeError) as caught:
        port.catalog()

    assert caught.value.code is native.Spine38NativeCode.RUNTIME_FAILURE
    assert caught.value.__cause__ is None


@pytest.mark.parametrize(
    ("method_name", "capacity_attribute", "payload_attribute"),
    [
        ("catalog", "animation_capacity_override", "animation_name_bytes_override"),
        ("skins", "skin_capacity_override", "skin_name_bytes_override"),
    ],
)
@pytest.mark.parametrize(
    ("capacity", "payload"),
    [
        (4, b"a\0b\0"),
        (4, b"a\0"),
        (4, b"abcd"),
        (1, b"\0"),
        (2, b"\xff\0"),
    ],
    ids=["embedded-nul", "unwritten-tail", "missing-terminator", "empty", "invalid-utf8"],
)
def test_native_binding_rejects_malformed_native_names(
    fake_library: FakeLibrary,
    snapshot: ExternalPetAssetSnapshot,
    method_name: str,
    capacity_attribute: str,
    payload_attribute: str,
    capacity: int,
    payload: bytes,
) -> None:
    native = importlib.import_module("sjtuclaw.infrastructure.spine38_native")
    setattr(fake_library, capacity_attribute, capacity)
    setattr(fake_library, payload_attribute, payload)
    port = native.Spine38NativeLibrary(fake_library).create(snapshot)

    with pytest.raises(native.Spine38NativeError) as caught:
        getattr(port, method_name)()

    assert caught.value.code is native.Spine38NativeCode.RUNTIME_FAILURE


def test_native_binding_close_is_idempotent_and_closed_ports_fail(
    fake_library: FakeLibrary,
    snapshot: ExternalPetAssetSnapshot,
) -> None:
    native = importlib.import_module("sjtuclaw.infrastructure.spine38_native")
    port = native.Spine38NativeLibrary(fake_library).create(snapshot)

    port.close()
    port.close()

    assert fake_library.destroy_count == 1
    with pytest.raises(native.Spine38NativeError) as caught:
        port.catalog()
    assert caught.value.code is native.Spine38NativeCode.CLOSED


def test_native_binding_finalizer_destroys_an_unclosed_handle_once(
    fake_library: FakeLibrary,
    snapshot: ExternalPetAssetSnapshot,
) -> None:
    native = importlib.import_module("sjtuclaw.infrastructure.spine38_native")
    port = native.Spine38NativeLibrary(fake_library).create(snapshot)
    port_reference = weakref.ref(port)

    del port
    gc.collect()

    assert port_reference() is None
    assert fake_library.destroy_count == 1


def test_native_binding_concurrent_close_calls_destroy_once(
    fake_library: FakeLibrary,
    snapshot: ExternalPetAssetSnapshot,
) -> None:
    native = importlib.import_module("sjtuclaw.infrastructure.spine38_native")
    port = native.Spine38NativeLibrary(fake_library).create(snapshot)
    port._closed = _TwoThreadFalseGate()
    failures: list[BaseException] = []

    def close_port() -> None:
        try:
            port.close()
        except BaseException as error:
            failures.append(error)

    threads = [threading.Thread(target=close_port) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2)

    assert not failures
    assert all(not thread.is_alive() for thread in threads)
    assert fake_library.destroy_count == 1


def test_native_binding_close_waits_for_complete_catalog_operation(
    fake_library: FakeLibrary,
    snapshot: ExternalPetAssetSnapshot,
) -> None:
    native = importlib.import_module("sjtuclaw.infrastructure.spine38_native")
    fake_library.animation_count_started = threading.Event()
    fake_library.animation_count_release = threading.Event()
    port = native.Spine38NativeLibrary(fake_library).create(snapshot)
    catalog_results: list[object] = []
    failures: list[BaseException] = []

    def read_catalog() -> None:
        try:
            catalog_results.append(port.catalog())
        except BaseException as error:
            failures.append(error)

    def close_port() -> None:
        try:
            port.close()
        except BaseException as error:
            failures.append(error)

    catalog_thread = threading.Thread(target=read_catalog)
    catalog_thread.start()
    assert fake_library.animation_count_started.wait(timeout=2)
    close_thread = threading.Thread(target=close_port)
    close_thread.start()

    destroyed_before_catalog_release = fake_library.destroyed.wait(timeout=0.2)
    fake_library.animation_count_release.set()
    catalog_thread.join(timeout=2)
    close_thread.join(timeout=2)

    assert not failures
    assert not catalog_thread.is_alive()
    assert not close_thread.is_alive()
    assert not destroyed_before_catalog_release
    assert len(catalog_results) == 1
    assert fake_library.destroy_count == 1
    assert fake_library.native_calls_after_destroy == 0
    with pytest.raises(native.Spine38NativeError) as caught:
        port.catalog()
    assert caught.value.code is native.Spine38NativeCode.CLOSED
    assert fake_library.native_calls_after_destroy == 0


def test_native_module_has_no_agent_imports() -> None:
    spine38_native = importlib.import_module("sjtuclaw.infrastructure.spine38_native")

    source = inspect.getsource(spine38_native)

    assert all(word not in source for word in ("AgentLoop", "Provider", "SecretStore"))
