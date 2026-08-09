"""Contract tests for the isolated Spine 3.8 ctypes catalog binding."""

from __future__ import annotations

import ctypes
import gc
import importlib
import inspect
import math
import weakref
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

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


class FakeLibrary:
    """In-process ABI fake; it replaces only the external DLL boundary."""

    def __init__(self) -> None:
        self.abi_version = 1
        self.create_code = 0
        self.animation_info_code = 0
        self.skin_info_code = 0
        self.bounds_code = 0
        self.animations = (("idle-猫", 1.25),)
        self.skins = ("default",)
        self.bounds = (-2.0, 3.0, 4.0, 5.0)
        self.destroy_count = 0
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

    def _animation_count(self, handle: object) -> int:
        self._assert_handle(handle)
        return len(self.animations)

    def _animation_name_size(self, handle: object, index: object) -> int:
        self._assert_handle(handle)
        name, _ = self.animations[cast(int, index)]
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
        if self.animation_info_code != 0:
            return self.animation_info_code
        animation_name, value = self.animations[cast(int, index)]
        encoded = animation_name.encode("utf-8") + b"\0"
        assert cast(int, capacity) == len(encoded)
        ctypes.memmove(cast(Any, name), encoded, len(encoded))
        ctypes.cast(cast(Any, duration), ctypes.POINTER(ctypes.c_float))[0] = value
        return 0

    def _skin_count(self, handle: object) -> int:
        self._assert_handle(handle)
        return len(self.skins)

    def _skin_name_size(self, handle: object, index: object) -> int:
        self._assert_handle(handle)
        return len(self.skins[cast(int, index)].encode("utf-8")) + 1

    def _skin_info(
        self,
        handle: object,
        index: object,
        name: object,
        capacity: object,
    ) -> int:
        self._assert_handle(handle)
        if self.skin_info_code != 0:
            return self.skin_info_code
        encoded = self.skins[cast(int, index)].encode("utf-8") + b"\0"
        assert cast(int, capacity) == len(encoded)
        ctypes.memmove(cast(Any, name), encoded, len(encoded))
        return 0

    def _setup_bounds(self, handle: object, bounds: object) -> int:
        self._assert_handle(handle)
        if self.bounds_code != 0:
            return self.bounds_code
        output = ctypes.cast(cast(Any, bounds), ctypes.POINTER(FakeBounds))[0]
        output.x, output.y, output.width, output.height = self.bounds
        return 0

    @staticmethod
    def _assert_handle(handle: object) -> None:
        assert ctypes.cast(cast(Any, handle), ctypes.c_void_p).value == 101


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


def test_native_module_has_no_agent_imports() -> None:
    spine38_native = importlib.import_module("sjtuclaw.infrastructure.spine38_native")

    source = inspect.getsource(spine38_native)

    assert all(word not in source for word in ("AgentLoop", "Provider", "SecretStore"))
