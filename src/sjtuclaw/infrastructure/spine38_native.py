"""Framework-neutral ctypes boundary for the Spine 3.8 Runtime bridge."""

from __future__ import annotations

import ctypes
import math
import threading
import weakref
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from typing import Protocol, cast

from sjtuclaw.application.pet_external_assets import ExternalPetAssetSnapshot

_EXPECTED_ABI_VERSION = 1
# Adapter safety limits bound catalog work even if a loaded DLL is corrupt.
_MAX_CATALOG_ENTRIES = 4096
_MAX_CATALOG_NAME_BYTES = 4096
_MAX_DRAW_COMMANDS = 4096
_MAX_DRAW_ELEMENTS = 4096
_MAX_PLAYBACK_EVENTS = 4096
_MAX_TRACK_INDEX = 255


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


class Spine38BlendMode(IntEnum):
    """Renderer-neutral slot compositing values fixed by the native ABI."""

    NORMAL = 0
    ADDITIVE = 1
    MULTIPLY = 2
    SCREEN = 3


class Spine38TextureFilter(IntEnum):
    UNKNOWN = 0
    NEAREST = 1
    LINEAR = 2


class Spine38NativeEventType(IntEnum):
    COMPLETE = 1
    LOOP_BOUNDARY = 2


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


@dataclass(frozen=True, slots=True)
class Spine38Vertex:
    x: float
    y: float
    u: float
    v: float
    r: int
    g: int
    b: int
    a: int


@dataclass(frozen=True, slots=True)
class Spine38DrawCommand:
    vertices: tuple[Spine38Vertex, ...]
    indices: tuple[int, ...]
    texture_page: int
    blend_mode: Spine38BlendMode
    draw_order: int


@dataclass(frozen=True, slots=True)
class Spine38NativePlaybackEvent:
    event_type: Spine38NativeEventType
    physical_name: str
    loop_ordinal: int


@dataclass(frozen=True, slots=True)
class Spine38TexturePageInfo:
    min_filter: Spine38TextureFilter
    mag_filter: Spine38TextureFilter


class Spine38CatalogNativePort(Protocol):
    def catalog(self) -> tuple[Spine38AnimationInfo, ...]: ...

    def skins(self) -> tuple[str, ...]: ...

    def setup_bounds(self) -> Spine38Bounds: ...

    def close(self) -> None: ...


class Spine38NativePort(Spine38CatalogNativePort, Protocol):
    def set_animation(self, track: int, name: str, loop: bool) -> None: ...

    def update(self, delta_seconds: float) -> None: ...

    def clear_track(self, track: int) -> None: ...

    def playback_events(self) -> tuple[Spine38NativePlaybackEvent, ...]: ...

    def texture_page_info(self) -> Spine38TexturePageInfo: ...

    def draw_commands(self) -> tuple[Spine38DrawCommand, ...]: ...


class _SjtuclawSpine38Bounds(ctypes.Structure):
    _fields_ = [
        ("x", ctypes.c_float),
        ("y", ctypes.c_float),
        ("width", ctypes.c_float),
        ("height", ctypes.c_float),
    ]


class _SjtuclawSpine38Vertex(ctypes.Structure):
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


class _SjtuclawSpine38DrawView(ctypes.Structure):
    _fields_ = [
        ("vertices", ctypes.POINTER(_SjtuclawSpine38Vertex)),
        ("vertex_count", ctypes.c_size_t),
        ("indices", ctypes.POINTER(ctypes.c_uint32)),
        ("index_count", ctypes.c_size_t),
        ("texture_page", ctypes.c_uint32),
        ("blend_mode", ctypes.c_uint32),
        ("draw_order", ctypes.c_int32),
    ]


class _SjtuclawSpine38EventView(ctypes.Structure):
    _fields_ = [
        ("event_type", ctypes.c_uint32),
        ("track", ctypes.c_uint32),
        ("loop_ordinal", ctypes.c_uint64),
        ("animation_name_utf8", ctypes.POINTER(ctypes.c_char)),
        ("animation_name_size", ctypes.c_size_t),
    ]


class _SjtuclawSpine38TexturePageView(ctypes.Structure):
    _fields_ = [
        ("min_filter", ctypes.c_uint32),
        ("mag_filter", ctypes.c_uint32),
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
    sjtuclaw_spine38_set_animation: _NativeFunction
    sjtuclaw_spine38_update: _NativeFunction
    sjtuclaw_spine38_clear_track: _NativeFunction
    sjtuclaw_spine38_event_count: _NativeFunction
    sjtuclaw_spine38_event_view: _NativeFunction
    sjtuclaw_spine38_texture_page_view: _NativeFunction
    sjtuclaw_spine38_draw_count: _NativeFunction
    sjtuclaw_spine38_draw_view: _NativeFunction


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
        except OSError:
            raise Spine38NativeError(Spine38NativeCode.DLL_PATH_INVALID) from None
        return cls(library)

    def create(self, snapshot: ExternalPetAssetSnapshot) -> Spine38NativePort:
        """Create a handle while retaining input buffers through the native call."""

        skeleton, atlas = self._validated_create_bytes(snapshot)
        skeleton_size = len(skeleton)
        try:
            skeleton_buffer = (ctypes.c_uint8 * skeleton_size).from_buffer_copy(skeleton)
            atlas_buffer = (ctypes.c_char * len(atlas)).from_buffer_copy(atlas)
        except (MemoryError, OverflowError):
            raise Spine38NativeError(Spine38NativeCode.RUNTIME_FAILURE) from None
        handle = ctypes.c_void_p()
        code = self._library.sjtuclaw_spine38_create(
            skeleton_buffer,
            skeleton_size,
            atlas_buffer,
            len(atlas),
            ctypes.byref(handle),
        )
        _require_ok(code)
        if handle.value is None:
            raise Spine38NativeError(Spine38NativeCode.RUNTIME_FAILURE)
        return _Spine38CatalogNativeHandle(self._library, handle, skeleton_size)

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
        library.sjtuclaw_spine38_set_animation.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_char),
            ctypes.c_size_t,
            ctypes.c_uint8,
        ]
        library.sjtuclaw_spine38_set_animation.restype = ctypes.c_int
        library.sjtuclaw_spine38_update.argtypes = [
            ctypes.c_void_p,
            ctypes.c_float,
        ]
        library.sjtuclaw_spine38_update.restype = ctypes.c_int
        library.sjtuclaw_spine38_clear_track.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
        ]
        library.sjtuclaw_spine38_clear_track.restype = ctypes.c_int
        library.sjtuclaw_spine38_event_count.argtypes = [ctypes.c_void_p]
        library.sjtuclaw_spine38_event_count.restype = ctypes.c_size_t
        library.sjtuclaw_spine38_event_view.argtypes = [
            ctypes.c_void_p,
            ctypes.c_size_t,
            ctypes.POINTER(_SjtuclawSpine38EventView),
            ctypes.c_size_t,
        ]
        library.sjtuclaw_spine38_event_view.restype = ctypes.c_int
        library.sjtuclaw_spine38_texture_page_view.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(_SjtuclawSpine38TexturePageView),
            ctypes.c_size_t,
        ]
        library.sjtuclaw_spine38_texture_page_view.restype = ctypes.c_int
        library.sjtuclaw_spine38_draw_count.argtypes = [ctypes.c_void_p]
        library.sjtuclaw_spine38_draw_count.restype = ctypes.c_size_t
        library.sjtuclaw_spine38_draw_view.argtypes = [
            ctypes.c_void_p,
            ctypes.c_size_t,
            ctypes.POINTER(_SjtuclawSpine38DrawView),
            ctypes.c_size_t,
        ]
        library.sjtuclaw_spine38_draw_view.restype = ctypes.c_int

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

    def __init__(
        self,
        library: _NativeLibrary,
        handle: ctypes.c_void_p,
        skeleton_size: int,
    ) -> None:
        self._library = library
        self._handle = handle
        self._catalog_entry_limit = min(_MAX_CATALOG_ENTRIES, skeleton_size)
        self._catalog_name_limit = min(_MAX_CATALOG_NAME_BYTES, skeleton_size)
        self._draw_command_limit = min(_MAX_DRAW_COMMANDS, skeleton_size)
        self._draw_element_limit = min(_MAX_DRAW_ELEMENTS, skeleton_size)
        self._playback_event_limit = min(_MAX_PLAYBACK_EVENTS, skeleton_size)
        self._lock = threading.RLock()
        self._closed = False
        self._finalizer = weakref.finalize(
            self,
            _destroy_unclosed_handle,
            library.sjtuclaw_spine38_destroy,
            handle,
        )

    def catalog(self) -> tuple[Spine38AnimationInfo, ...]:
        with self._lock:
            handle = self._require_open()
            count = _bounded_native_size(
                self._library.sjtuclaw_spine38_animation_count(handle),
                minimum=0,
                maximum=self._catalog_entry_limit,
            )
            try:
                return tuple(self._animation_info(handle, index) for index in range(count))
            except (MemoryError, OverflowError):
                raise Spine38NativeError(Spine38NativeCode.RUNTIME_FAILURE) from None

    def skins(self) -> tuple[str, ...]:
        with self._lock:
            handle = self._require_open()
            count = _bounded_native_size(
                self._library.sjtuclaw_spine38_skin_count(handle),
                minimum=0,
                maximum=self._catalog_entry_limit,
            )
            try:
                return tuple(self._skin_info(handle, index) for index in range(count))
            except (MemoryError, OverflowError):
                raise Spine38NativeError(Spine38NativeCode.RUNTIME_FAILURE) from None

    def setup_bounds(self) -> Spine38Bounds:
        with self._lock:
            handle = self._require_open()
            raw_bounds = _SjtuclawSpine38Bounds()
            _require_ok(
                self._library.sjtuclaw_spine38_setup_bounds(
                    handle,
                    ctypes.byref(raw_bounds),
                )
            )
            values = (raw_bounds.x, raw_bounds.y, raw_bounds.width, raw_bounds.height)
            if not all(math.isfinite(value) for value in values) or any(
                value <= 0.0 for value in values[2:]
            ):
                raise Spine38NativeError(Spine38NativeCode.RUNTIME_FAILURE)
            return Spine38Bounds(*values)

    def set_animation(self, track: int, name: str, loop: bool) -> None:
        with self._lock:
            handle = self._require_open()
            if (
                isinstance(track, bool)
                or not isinstance(track, int)
                or track < 0
                or track > _MAX_TRACK_INDEX
                or not isinstance(name, str)
                or not name
                or "\0" in name
                or type(loop) is not bool
            ):
                raise Spine38NativeError(Spine38NativeCode.INVALID_ARGUMENT)
            try:
                encoded_name = name.encode("utf-8")
            except UnicodeEncodeError:
                raise Spine38NativeError(Spine38NativeCode.INVALID_ARGUMENT) from None
            if not encoded_name or len(encoded_name) > self._catalog_name_limit:
                raise Spine38NativeError(Spine38NativeCode.INVALID_ARGUMENT)
            try:
                name_buffer = (ctypes.c_char * len(encoded_name)).from_buffer_copy(
                    encoded_name
                )
            except (MemoryError, OverflowError):
                raise Spine38NativeError(Spine38NativeCode.RUNTIME_FAILURE) from None
            _require_ok(
                self._library.sjtuclaw_spine38_set_animation(
                    handle,
                    track,
                    name_buffer,
                    len(encoded_name),
                    int(loop),
                )
            )

    def update(self, delta_seconds: float) -> None:
        with self._lock:
            handle = self._require_open()
            if isinstance(delta_seconds, bool) or not isinstance(
                delta_seconds, (int, float)
            ):
                raise Spine38NativeError(Spine38NativeCode.INVALID_ARGUMENT)
            value = float(delta_seconds)
            if not math.isfinite(value) or value < 0.0:
                raise Spine38NativeError(Spine38NativeCode.INVALID_ARGUMENT)
            narrowed = ctypes.c_float(value).value
            if not math.isfinite(narrowed) or narrowed < 0.0:
                raise Spine38NativeError(Spine38NativeCode.INVALID_ARGUMENT)
            _require_ok(self._library.sjtuclaw_spine38_update(handle, narrowed))

    def clear_track(self, track: int) -> None:
        with self._lock:
            handle = self._require_open()
            if (
                isinstance(track, bool)
                or not isinstance(track, int)
                or track < 0
                or track > _MAX_TRACK_INDEX
            ):
                raise Spine38NativeError(Spine38NativeCode.INVALID_ARGUMENT)
            _require_ok(self._library.sjtuclaw_spine38_clear_track(handle, track))

    def playback_events(self) -> tuple[Spine38NativePlaybackEvent, ...]:
        with self._lock:
            handle = self._require_open()
            count = _bounded_native_size(
                self._library.sjtuclaw_spine38_event_count(handle),
                minimum=0,
                maximum=self._playback_event_limit,
            )
            try:
                return tuple(self._playback_event(handle, index) for index in range(count))
            except (MemoryError, OverflowError):
                raise Spine38NativeError(Spine38NativeCode.RUNTIME_FAILURE) from None

    def draw_commands(self) -> tuple[Spine38DrawCommand, ...]:
        with self._lock:
            handle = self._require_open()
            count = _bounded_native_size(
                self._library.sjtuclaw_spine38_draw_count(handle),
                minimum=0,
                maximum=self._draw_command_limit,
            )
            try:
                return tuple(self._draw_command(handle, index) for index in range(count))
            except (MemoryError, OverflowError):
                raise Spine38NativeError(Spine38NativeCode.RUNTIME_FAILURE) from None

    def texture_page_info(self) -> Spine38TexturePageInfo:
        with self._lock:
            handle = self._require_open()
            raw = _SjtuclawSpine38TexturePageView()
            _require_ok(
                self._library.sjtuclaw_spine38_texture_page_view(
                    handle,
                    ctypes.byref(raw),
                    ctypes.sizeof(raw),
                )
            )
            try:
                return Spine38TexturePageInfo(
                    Spine38TextureFilter(raw.min_filter),
                    Spine38TextureFilter(raw.mag_filter),
                )
            except ValueError:
                raise Spine38NativeError(
                    Spine38NativeCode.RUNTIME_FAILURE
                ) from None

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._finalizer()

    def _playback_event(
        self,
        handle: ctypes.c_void_p,
        index: int,
    ) -> Spine38NativePlaybackEvent:
        raw = _SjtuclawSpine38EventView()
        _require_ok(
            self._library.sjtuclaw_spine38_event_view(
                handle,
                index,
                ctypes.byref(raw),
                ctypes.sizeof(raw),
            )
        )
        size = _bounded_native_size(
            raw.animation_name_size,
            minimum=1,
            maximum=self._catalog_name_limit,
        )
        if raw.track != 0 or not raw.animation_name_utf8:
            raise Spine38NativeError(Spine38NativeCode.RUNTIME_FAILURE)
        try:
            event_type = Spine38NativeEventType(raw.event_type)
            encoded = ctypes.string_at(raw.animation_name_utf8, size)
            name = encoded.decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            raise Spine38NativeError(Spine38NativeCode.RUNTIME_FAILURE) from None
        invalid_ordinal = (
            event_type is Spine38NativeEventType.COMPLETE
            and raw.loop_ordinal != 0
        ) or (
            event_type is Spine38NativeEventType.LOOP_BOUNDARY
            and raw.loop_ordinal == 0
        )
        if "\0" in name or invalid_ordinal:
            raise Spine38NativeError(Spine38NativeCode.RUNTIME_FAILURE)
        return Spine38NativePlaybackEvent(event_type, name, int(raw.loop_ordinal))

    def _animation_info(
        self,
        handle: ctypes.c_void_p,
        index: int,
    ) -> Spine38AnimationInfo:
        capacity = _bounded_native_size(
            self._library.sjtuclaw_spine38_animation_name_size(handle, index),
            minimum=2,
            maximum=self._catalog_name_limit,
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
        capacity = _bounded_native_size(
            self._library.sjtuclaw_spine38_skin_name_size(handle, index),
            minimum=2,
            maximum=self._catalog_name_limit,
        )
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

    def _draw_command(
        self,
        handle: ctypes.c_void_p,
        index: int,
    ) -> Spine38DrawCommand:
        raw_view = _SjtuclawSpine38DrawView()
        _require_ok(
            self._library.sjtuclaw_spine38_draw_view(
                handle,
                index,
                ctypes.byref(raw_view),
                ctypes.sizeof(raw_view),
            )
        )
        vertex_count = _bounded_native_size(
            raw_view.vertex_count,
            minimum=1,
            maximum=self._draw_element_limit,
        )
        index_count = _bounded_native_size(
            raw_view.index_count,
            minimum=3,
            maximum=self._draw_element_limit,
        )
        if (
            not raw_view.vertices
            or not raw_view.indices
            or index_count % 3 != 0
            or raw_view.texture_page != 0
            or raw_view.draw_order < 0
            or raw_view.draw_order > self._draw_element_limit
        ):
            raise Spine38NativeError(Spine38NativeCode.RUNTIME_FAILURE)
        try:
            blend_mode = Spine38BlendMode(raw_view.blend_mode)
            vertices = tuple(
                Spine38Vertex(
                    float(raw_view.vertices[item].x),
                    float(raw_view.vertices[item].y),
                    float(raw_view.vertices[item].u),
                    float(raw_view.vertices[item].v),
                    int(raw_view.vertices[item].r),
                    int(raw_view.vertices[item].g),
                    int(raw_view.vertices[item].b),
                    int(raw_view.vertices[item].a),
                )
                for item in range(vertex_count)
            )
            indices = tuple(int(raw_view.indices[item]) for item in range(index_count))
        except (MemoryError, OverflowError, ValueError):
            raise Spine38NativeError(Spine38NativeCode.RUNTIME_FAILURE) from None
        if not all(
            math.isfinite(value)
            for vertex in vertices
            for value in (vertex.x, vertex.y, vertex.u, vertex.v)
        ) or any(item < 0 or item >= vertex_count for item in indices):
            raise Spine38NativeError(Spine38NativeCode.RUNTIME_FAILURE)
        return Spine38DrawCommand(
            vertices=vertices,
            indices=indices,
            texture_page=int(raw_view.texture_page),
            blend_mode=blend_mode,
            draw_order=int(raw_view.draw_order),
        )

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


def _bounded_native_size(raw_size: object, *, minimum: int, maximum: int) -> int:
    try:
        size = int(cast(int, raw_size))
    except (MemoryError, OverflowError, TypeError, ValueError):
        raise Spine38NativeError(Spine38NativeCode.RUNTIME_FAILURE) from None
    if size < minimum or size > maximum:
        raise Spine38NativeError(Spine38NativeCode.RUNTIME_FAILURE)
    return size


def _name_buffer(capacity: int) -> ctypes.Array[ctypes.c_char]:
    try:
        buffer = (ctypes.c_char * capacity)()
        ctypes.memset(buffer, 0xFF, capacity)
    except (MemoryError, OverflowError):
        raise Spine38NativeError(Spine38NativeCode.RUNTIME_FAILURE) from None
    return buffer


def _decode_name(buffer: ctypes.Array[ctypes.c_char]) -> str:
    raw = bytes(buffer)
    if len(raw) < 2 or raw[-1] != 0 or b"\0" in raw[:-1]:
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
