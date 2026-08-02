"""Windows no-follow filesystem backend for external pet asset bundles."""

from __future__ import annotations

import ctypes
import msvcrt
import os
from ctypes import wintypes
from pathlib import PureWindowsPath
from typing import Any, BinaryIO, ClassVar

from sjtuclaw.application.pet_external_assets import (
    ExternalAssetFilesystemError,
    ExternalAssetRootHandle,
    ExternalFileIdentity,
    ExternalPetAssetStatus,
    ReadOnlyExternalAssetHandle,
)

_GENERIC_READ = 0x80000000
_FILE_SHARE_READ = 0x00000001
_OPEN_EXISTING = 3
_FILE_ATTRIBUTE_DIRECTORY = 0x00000010
_FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
_FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
_FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
_FILE_FLAG_SEQUENTIAL_SCAN = 0x08000000
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
_ERROR_FILE_NOT_FOUND = 2
_ERROR_PATH_NOT_FOUND = 3
_ERROR_HANDLE_EOF = 38
_FIND_STREAM_INFO_STANDARD = 0


class _FileTime(ctypes.Structure):
    _fields_: ClassVar[list[tuple[str, Any]]] = [
        ("low", wintypes.DWORD),
        ("high", wintypes.DWORD),
    ]


class _ByHandleFileInformation(ctypes.Structure):
    _fields_: ClassVar[list[tuple[str, Any]]] = [
        ("attributes", wintypes.DWORD),
        ("creation_time", _FileTime),
        ("access_time", _FileTime),
        ("write_time", _FileTime),
        ("volume_serial", wintypes.DWORD),
        ("size_high", wintypes.DWORD),
        ("size_low", wintypes.DWORD),
        ("link_count", wintypes.DWORD),
        ("file_index_high", wintypes.DWORD),
        ("file_index_low", wintypes.DWORD),
    ]


class _Win32FindStreamData(ctypes.Structure):
    _fields_: ClassVar[list[tuple[str, Any]]] = [
        ("stream_size", ctypes.c_longlong),
        ("stream_name", wintypes.WCHAR * 296),
    ]


class _WindowsBindings:
    def __init__(self) -> None:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateFileW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.c_void_p,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        ]
        kernel32.CreateFileW.restype = wintypes.HANDLE
        kernel32.GetFileInformationByHandle.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(_ByHandleFileInformation),
        ]
        kernel32.GetFileInformationByHandle.restype = wintypes.BOOL
        kernel32.GetFinalPathNameByHandleW.argtypes = [
            wintypes.HANDLE,
            wintypes.LPWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
        ]
        kernel32.GetFinalPathNameByHandleW.restype = wintypes.DWORD
        kernel32.FindFirstStreamW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            ctypes.POINTER(_Win32FindStreamData),
            wintypes.DWORD,
        ]
        kernel32.FindFirstStreamW.restype = wintypes.HANDLE
        kernel32.FindNextStreamW.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(_Win32FindStreamData),
        ]
        kernel32.FindNextStreamW.restype = wintypes.BOOL
        kernel32.FindClose.argtypes = [wintypes.HANDLE]
        kernel32.FindClose.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        self.kernel32: Any = kernel32

    def open_handle(self, path: str, *, directory: bool) -> int:
        flags = _FILE_FLAG_OPEN_REPARSE_POINT
        if directory:
            flags |= _FILE_FLAG_BACKUP_SEMANTICS
        else:
            flags |= _FILE_FLAG_SEQUENTIAL_SCAN
        handle = self.kernel32.CreateFileW(
            path,
            _GENERIC_READ,
            _FILE_SHARE_READ,
            None,
            _OPEN_EXISTING,
            flags,
            None,
        )
        if handle == _INVALID_HANDLE_VALUE:
            error = int(ctypes.get_last_error())
            status = (
                ExternalPetAssetStatus.MISSING
                if error in {_ERROR_FILE_NOT_FOUND, _ERROR_PATH_NOT_FOUND}
                else ExternalPetAssetStatus.READ_FAILED
            )
            raise ExternalAssetFilesystemError(status)
        return int(handle)

    def close_handle(self, handle: int) -> None:
        self.kernel32.CloseHandle(wintypes.HANDLE(handle))

    def information(self, handle: int) -> _ByHandleFileInformation:
        value = _ByHandleFileInformation()
        if not self.kernel32.GetFileInformationByHandle(
            wintypes.HANDLE(handle),
            ctypes.byref(value),
        ):
            raise ExternalAssetFilesystemError(
                ExternalPetAssetStatus.READ_FAILED
            )
        return value

    def final_path(self, handle: int) -> str:
        required = int(
            self.kernel32.GetFinalPathNameByHandleW(
                wintypes.HANDLE(handle),
                None,
                0,
                0,
            )
        )
        if required <= 0 or required > 32_768:
            raise ExternalAssetFilesystemError(
                ExternalPetAssetStatus.READ_FAILED
            )
        buffer = ctypes.create_unicode_buffer(required + 1)
        written = int(
            self.kernel32.GetFinalPathNameByHandleW(
                wintypes.HANDLE(handle),
                buffer,
                len(buffer),
                0,
            )
        )
        if written <= 0 or written >= len(buffer):
            raise ExternalAssetFilesystemError(
                ExternalPetAssetStatus.READ_FAILED
            )
        value = buffer.value
        if value.startswith("\\\\?\\"):
            value = value[4:]
        return os.path.normcase(os.path.abspath(value))

    def has_named_streams(self, path: str) -> bool:
        value = _Win32FindStreamData()
        search = self.kernel32.FindFirstStreamW(
            path,
            _FIND_STREAM_INFO_STANDARD,
            ctypes.byref(value),
            0,
        )
        if search == _INVALID_HANDLE_VALUE:
            if int(ctypes.get_last_error()) == _ERROR_HANDLE_EOF:
                return False
            raise ExternalAssetFilesystemError(
                ExternalPetAssetStatus.READ_FAILED
            )
        try:
            while True:
                if value.stream_name != "::$DATA":
                    return True
                if not self.kernel32.FindNextStreamW(
                    search,
                    ctypes.byref(value),
                ):
                    return False
        finally:
            self.kernel32.FindClose(search)


class _WindowsRootHandle:
    def __init__(
        self,
        bindings: _WindowsBindings,
        handle: int,
        final_path: str,
        identity: ExternalFileIdentity,
    ) -> None:
        self._bindings = bindings
        self._handle = handle
        self._final_path = final_path
        self._identity = identity
        self._closed = False

    @property
    def final_path(self) -> str:
        return self._final_path

    @property
    def identity(self) -> ExternalFileIdentity:
        return self._identity

    @property
    def native_handle(self) -> int:
        return self._handle

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._bindings.close_handle(self._handle)

    def __repr__(self) -> str:
        return f"_WindowsRootHandle(closed={self._closed!r})"


class _WindowsFileHandle:
    def __init__(
        self,
        bindings: _WindowsBindings,
        reader: BinaryIO,
        final_path: str,
        identity: ExternalFileIdentity,
    ) -> None:
        self._bindings = bindings
        self._reader = reader
        self._final_path = final_path
        self._identity = identity
        self._closed = False

    @property
    def identity(self) -> ExternalFileIdentity:
        return self._identity

    def current_identity(self) -> ExternalFileIdentity:
        if self._closed:
            raise ExternalAssetFilesystemError(
                ExternalPetAssetStatus.READ_FAILED
            )
        native = int(msvcrt.get_osfhandle(self._reader.fileno()))
        return _identity_from_information(self._bindings.information(native))

    def has_alternate_data_streams(self) -> bool:
        if self._closed:
            raise ExternalAssetFilesystemError(
                ExternalPetAssetStatus.READ_FAILED
            )
        return self._bindings.has_named_streams(self._final_path)

    def read(self, size: int = -1) -> bytes:
        return self._reader.read(size)

    def seek(self, offset: int) -> int:
        return self._reader.seek(offset)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._reader.close()

    def __repr__(self) -> str:
        return f"_WindowsFileHandle(closed={self._closed!r})"


class WindowsExternalPetAssetFilesystem:
    """Open only explicitly named files and retain restrictive Win32 handles."""

    def __init__(self) -> None:
        if os.name != "nt":
            raise RuntimeError("Windows filesystem backend is unavailable.")
        self._bindings = _WindowsBindings()

    def open_root(self, root: str) -> ExternalAssetRootHandle:
        handle = self._bindings.open_handle(root, directory=True)
        try:
            information = self._bindings.information(handle)
            if information.attributes & _FILE_ATTRIBUTE_REPARSE_POINT:
                raise ExternalAssetFilesystemError(
                    ExternalPetAssetStatus.REPARSE_POINT
                )
            if not information.attributes & _FILE_ATTRIBUTE_DIRECTORY:
                raise ExternalAssetFilesystemError(
                    ExternalPetAssetStatus.ROOT_INVALID
                )
            return _WindowsRootHandle(
                self._bindings,
                handle,
                self._bindings.final_path(handle),
                _identity_from_information(information),
            )
        except Exception:
            self._bindings.close_handle(handle)
            raise

    def open_file(
        self,
        root: ExternalAssetRootHandle,
        filename: str,
    ) -> ReadOnlyExternalAssetHandle:
        if not isinstance(root, _WindowsRootHandle):
            raise ExternalAssetFilesystemError(
                ExternalPetAssetStatus.ROOT_INVALID
            )
        current_root = _identity_from_information(
            self._bindings.information(root.native_handle)
        )
        if current_root != root.identity:
            raise ExternalAssetFilesystemError(
                ExternalPetAssetStatus.CHANGED_DURING_READ
            )
        candidate = str(PureWindowsPath(root.final_path) / filename)
        handle = self._bindings.open_handle(candidate, directory=False)
        transferred = False
        try:
            information = self._bindings.information(handle)
            if information.attributes & _FILE_ATTRIBUTE_REPARSE_POINT:
                raise ExternalAssetFilesystemError(
                    ExternalPetAssetStatus.REPARSE_POINT
                )
            if information.attributes & _FILE_ATTRIBUTE_DIRECTORY:
                raise ExternalAssetFilesystemError(
                    ExternalPetAssetStatus.NOT_REGULAR
                )
            identity = _identity_from_information(information)
            if identity.link_count != 1:
                raise ExternalAssetFilesystemError(
                    ExternalPetAssetStatus.HARDLINK_INVALID
                )
            final_path = self._bindings.final_path(handle)
            if os.path.normcase(os.path.dirname(final_path)) != os.path.normcase(
                root.final_path
            ):
                raise ExternalAssetFilesystemError(
                    ExternalPetAssetStatus.PATH_ESCAPE
                )
            descriptor = msvcrt.open_osfhandle(
                handle,
                os.O_RDONLY | os.O_BINARY | getattr(os, "O_NOINHERIT", 0),
            )
            transferred = True
            reader = os.fdopen(descriptor, "rb", buffering=0)
            return _WindowsFileHandle(
                self._bindings,
                reader,
                final_path,
                identity,
            )
        except Exception:
            if not transferred:
                self._bindings.close_handle(handle)
            raise


def _identity_from_information(
    value: _ByHandleFileInformation,
) -> ExternalFileIdentity:
    return ExternalFileIdentity(
        volume_id=int(value.volume_serial),
        file_id=(int(value.file_index_high) << 32) | int(value.file_index_low),
        size_bytes=(int(value.size_high) << 32) | int(value.size_low),
        link_count=int(value.link_count),
        modified_ticks=(int(value.write_time.high) << 32)
        | int(value.write_time.low),
    )
