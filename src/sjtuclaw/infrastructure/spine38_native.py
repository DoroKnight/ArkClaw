"""Framework-neutral ctypes boundary for the Spine 3.8 catalog bridge."""

from __future__ import annotations

import ctypes
import math
import weakref
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from typing import Protocol, cast

from sjtuclaw.application.pet_external_assets import ExternalPetAssetSnapshot

_EXPECTED_ABI_VERSION = 1


class Spine38NativeCode(IntEnum):
    """Fixed bridge and adapter failure codes safe to surface to callers."""

    OK = 0
    INVALID_ARGUMENT = 1
    ATLAS_LOAD_FAILED = 2
    SKELETON_LOAD_FAILED = 3
    ANIMATION_NOT_FOUND = 4
    RUNTIME_FAILURE = 5
    ABI_MISMATCH = 6
    DLL_PATH_INVALID = 7
    CLOSED = 8


class Spine38NativeError(RuntimeError):
    """A fixed-code error that intentionally contains no native diagnostics."""

    def __init__(self, code: Spine38NativeCode) -> None:
        super().__init__(code.name.lower())
        self.code = code


@dataclass(frozen=True, slots=True)
class Spine38AnimationInfo:
    name: str
    duration_seconds: float


@dataclass(frozen=True, slots=True)
class Spine38Bounds:
    x: float
    y: float
    width: float
    height: float


class Spine38CatalogNativePort(Protocol):
    def catalog(self) -> tuple[Spine38AnimationInfo, ...]: ...

    def skins(self) -> tuple[str, ...]: ...

    def setup_bounds(self) -> Spine38Bounds: ...

    def close(self) -> None: ...


class _SjtuclawSpine38Bounds(ctypes.Structure):
    _fields_ = [
        ("x", ctypes.c_float),
        ("y", ctypes.c_float),
        ("width", ctypes.c_float),
        ("height", ctypes.c_float),
    ]


class _NativeFunction(Protocol):
    argtypes: list[object]
    restype: object | None

    def __call__(self, *args: object) -> object: ...


class _NativeLibrary(Protocol):
    sjtuclaw_spine38_abi_version: _NativeFunction
    sjtuclaw_spine38_create: _NativeFunction
    sjtuclaw_spine38_destroy: _NativeFunction
    sjtuclaw_spine38_animation_count: _NativeFunction
    sjtuclaw_spine38_animation_name_size: _NativeFunction
    sjtuclaw_spine38_animation_info: _NativeFunction
    sjtuclaw_spine38_skin_count: _NativeFunction
    sjtuclaw_spine38_skin_name_size: _NativeFunction
    sjtuclaw_spine38_skin_info: _NativeFunction
    sjtuclaw_spine38_setup_bounds: _NativeFunction


class Spine38NativeLibrary:
    """Loaded bridge library with an explicit ABI check before handle creation."""

    def __init__(self, library: _NativeLibrary) -> None:
        self._library = library
        try:
            self._declare_signatures()
            abi_version = int(cast(int, self._library.sjtuclaw_spine38_abi_version()))
        except (AttributeError, TypeError, ValueError):
            raise Spine38NativeError(Spine38NativeCode.ABI_MISMATCH) from None
        if abi_version != _EXPECTED_ABI_VERSION:
            raise Spine38NativeError(Spine38NativeCode.ABI_MISMATCH)

    @classmethod
    def from_dll_path(cls, dll_path: str | Path) -> Spine38NativeLibrary:
        """Load only an existing, explicitly absolute bridge DLL path."""

        path = Path(dll_path)
        if not path.is_absolute() or not path.is_file():
            raise Spine38NativeError(Spine38NativeCode.DLL_PATH_INVALID)
        try:
            library = cast(_NativeLibrary, ctypes.CDLL(str(path)))
        except OSError as error:
            raise Spine38NativeError(Spine38NativeCode.DLL_PATH_INVALID) from error
        return cls(library)

    def create(self, snapshot: ExternalPetAssetSnapshot) -> Spine38CatalogNativePort:
        """Create a handle while retaining input buffers through the native call."""

        skeleton, atlas = self._validated_create_bytes(snapshot)
        skeleton_buffer = (ctypes.c_uint8 * len(skeleton)).from_buffer_copy(skeleton)
        atlas_buffer = (ctypes.c_char * len(atlas)).from_buffer_copy(atlas)
        handle = ctypes.c_void_p()
        code = self._library.sjtuclaw_spine38_create(
            skeleton_buffer,
            len(skeleton),
            atlas_buffer,
            len(atlas),
            ctypes.byref(handle),
        )
        _require_ok(code)
        if handle.value is None:
            raise Spine38NativeError(Spine38NativeCode.RUNTIME_FAILURE)
        return _Spine38CatalogNativeHandle(self._library, handle)

    def _declare_signatures(self) -> None:
        library = self._library
        library.sjtuclaw_spine38_abi_version.argtypes = []
        library.sjtuclaw_spine38_abi_version.restype = ctypes.c_uint32
        library.sjtuclaw_spine38_create.argtypes = [
            ctypes.POINTER(ctypes.c_uint8),
            ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_char),
            ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        library.sjtuclaw_spine38_create.restype = ctypes.c_int
        library.sjtuclaw_spine38_destroy.argtypes = [ctypes.c_void_p]
        library.sjtuclaw_spine38_destroy.restype = None
        library.sjtuclaw_spine38_animation_count.argtypes = [ctypes.c_void_p]
        library.sjtuclaw_spine38_animation_count.restype = ctypes.c_size_t
        library.sjtuclaw_spine38_animation_name_size.argtypes = [
            ctypes.c_void_p,
            ctypes.c_size_t,
        ]
        library.sjtuclaw_spine38_animation_name_size.restype = ctypes.c_size_t
        library.sjtuclaw_spine38_animation_info.argtypes = [
            ctypes.c_void_p,
            ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_char),
            ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_float),
        ]
        library.sjtuclaw_spine38_animation_info.restype = ctypes.c_int
        library.sjtuclaw_spine38_skin_count.argtypes = [ctypes.c_void_p]
        library.sjtuclaw_spine38_skin_count.restype = ctypes.c_size_t
        library.sjtuclaw_spine38_skin_name_size.argtypes = [
            ctypes.c_void_p,
            ctypes.c_size_t,
        ]
        library.sjtuclaw_spine38_skin_name_size.restype = ctypes.c_size_t
        library.sjtuclaw_spine38_skin_info.argtypes = [
            ctypes.c_void_p,
            ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_char),
            ctypes.c_size_t,
        ]
        library.sjtuclaw_spine38_skin_info.restype = ctypes.c_int
        library.sjtuclaw_spine38_setup_bounds.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(_SjtuclawSpine38Bounds),
        ]
        library.sjtuclaw_spine38_setup_bounds.restype = ctypes.c_int

    @staticmethod
    def _validated_create_bytes(snapshot: ExternalPetAssetSnapshot) -> tuple[bytes, bytes]:
        if not isinstance(snapshot, ExternalPetAssetSnapshot):
            raise Spine38NativeError(Spine38NativeCode.INVALID_ARGUMENT)
        values = (
            snapshot.skeleton_bytes,
            snapshot.atlas_bytes,
            snapshot.texture_bytes,
        )
        if not all(isinstance(value, bytes) for value in values):
            raise Spine38NativeError(Spine38NativeCode.INVALID_ARGUMENT)
        if not snapshot.skeleton_bytes or not snapshot.atlas_bytes:
            raise Spine38NativeError(Spine38NativeCode.INVALID_ARGUMENT)
        return snapshot.skeleton_bytes, snapshot.atlas_bytes


class _Spine38CatalogNativeHandle:
    """Own one opaque native handle; the finalizer is only a leak fallback."""

    def __init__(self, library: _NativeLibrary, handle: ctypes.c_void_p) -> None:
        self._library = library
        self._handle = handle
        self._closed = False
        self._finalizer = weakref.finalize(
            self,
            _destroy_unclosed_handle,
            library.sjtuclaw_spine38_destroy,
            handle,
        )

    def catalog(self) -> tuple[Spine38AnimationInfo, ...]:
        handle = self._require_open()
        count = int(cast(int, self._library.sjtuclaw_spine38_animation_count(handle)))
        return tuple(self._animation_info(handle, index) for index in range(count))

    def skins(self) -> tuple[str, ...]:
        handle = self._require_open()
        count = int(cast(int, self._library.sjtuclaw_spine38_skin_count(handle)))
        return tuple(self._skin_info(handle, index) for index in range(count))

    def setup_bounds(self) -> Spine38Bounds:
        handle = self._require_open()
        raw_bounds = _SjtuclawSpine38Bounds()
        _require_ok(self._library.sjtuclaw_spine38_setup_bounds(handle, ctypes.byref(raw_bounds)))
        values = (raw_bounds.x, raw_bounds.y, raw_bounds.width, raw_bounds.height)
        if not all(math.isfinite(value) for value in values) or any(
            value <= 0.0 for value in values[2:]
        ):
            raise Spine38NativeError(Spine38NativeCode.RUNTIME_FAILURE)
        return Spine38Bounds(*values)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._finalizer.detach()
        _destroy_unclosed_handle(self._library.sjtuclaw_spine38_destroy, self._handle)

    def _animation_info(
        self,
        handle: ctypes.c_void_p,
        index: int,
    ) -> Spine38AnimationInfo:
        capacity = int(
            cast(int, self._library.sjtuclaw_spine38_animation_name_size(handle, index))
        )
        name_buffer = _name_buffer(capacity)
        duration = ctypes.c_float()
        _require_ok(
            self._library.sjtuclaw_spine38_animation_info(
                handle,
                index,
                name_buffer,
                capacity,
                ctypes.byref(duration),
            )
        )
        value = float(duration.value)
        if not math.isfinite(value) or value <= 0.0:
            raise Spine38NativeError(Spine38NativeCode.RUNTIME_FAILURE)
        return Spine38AnimationInfo(_decode_name(name_buffer), value)

    def _skin_info(self, handle: ctypes.c_void_p, index: int) -> str:
        capacity = int(cast(int, self._library.sjtuclaw_spine38_skin_name_size(handle, index)))
        name_buffer = _name_buffer(capacity)
        _require_ok(
            self._library.sjtuclaw_spine38_skin_info(
                handle,
                index,
                name_buffer,
                capacity,
            )
        )
        return _decode_name(name_buffer)

    def _require_open(self) -> ctypes.c_void_p:
        if self._closed:
            raise Spine38NativeError(Spine38NativeCode.CLOSED)
        return self._handle


def _require_ok(raw_code: object) -> None:
    try:
        code = Spine38NativeCode(int(cast(int, raw_code)))
    except (TypeError, ValueError):
        raise Spine38NativeError(Spine38NativeCode.RUNTIME_FAILURE) from None
    if code.value > Spine38NativeCode.RUNTIME_FAILURE.value:
        raise Spine38NativeError(Spine38NativeCode.RUNTIME_FAILURE)
    if code is not Spine38NativeCode.OK:
        raise Spine38NativeError(code)


def _name_buffer(capacity: int) -> ctypes.Array[ctypes.c_char]:
    if capacity <= 1:
        raise Spine38NativeError(Spine38NativeCode.RUNTIME_FAILURE)
    return (ctypes.c_char * capacity)()


def _decode_name(buffer: ctypes.Array[ctypes.c_char]) -> str:
    raw = bytes(buffer)
    if not raw or raw[-1] != 0:
        raise Spine38NativeError(Spine38NativeCode.RUNTIME_FAILURE)
    try:
        name = raw[:-1].decode("utf-8")
    except UnicodeDecodeError:
        raise Spine38NativeError(Spine38NativeCode.RUNTIME_FAILURE) from None
    if not name:
        raise Spine38NativeError(Spine38NativeCode.RUNTIME_FAILURE)
    return name


def _destroy_unclosed_handle(destroy: _NativeFunction, handle: ctypes.c_void_p) -> None:
    try:
        destroy(handle)
    except Exception:
        return
