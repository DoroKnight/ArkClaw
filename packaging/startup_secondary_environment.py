"""Deterministic, redacted environment model for startup secondary probes."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Final

_REDIRECT_NAMES: Final = (
    "TEMP",
    "TMP",
    "TMPDIR",
    "APPDATA",
    "LOCALAPPDATA",
    "HOME",
    "USERPROFILE",
)
_FILTERED_NAMES: Final = frozenset(
    {
        "PYTHONHOME",
        "PYTHONPATH",
        "VIRTUAL_ENV",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "NO_PROXY",
    }
)
_SENSITIVE_MARKERS: Final = (
    "API_KEY",
    "AUTHORIZATION",
    "CREDENTIAL",
    "PASSWORD",
    "SECRET",
    "TOKEN",
    "COOKIE",
)


class CanonicalEnvironmentError(ValueError):
    """A fixed, non-sensitive environment construction failure."""


class LaunchContextMismatch(ValueError):
    """A fixed, non-sensitive process identity mismatch."""


class ProbeLifecycleError(RuntimeError):
    """A fixed failure for retry, ordering, or PID identity violations."""


@dataclass(frozen=True, slots=True)
class EnvironmentManifest:
    """Only key names and one-way value digests, never environment values."""

    key_names: tuple[str, ...]
    value_sha256: Mapping[str, str]
    key_count: int
    duplicate_key_count: int
    repository_redirect_count: int
    outside_repository_path_count: int
    aggregate_sha256: str

    def to_safe_dict(self) -> dict[str, object]:
        return {
            "schema": 1,
            "key_names": list(self.key_names),
            "value_sha256": dict(self.value_sha256),
            "key_count": self.key_count,
            "duplicate_key_count": self.duplicate_key_count,
            "repository_redirect_count": self.repository_redirect_count,
            "outside_repository_path_count": (
                self.outside_repository_path_count
            ),
            "aggregate_sha256": self.aggregate_sha256,
            "environment_values_recorded": False,
        }


@dataclass(frozen=True, slots=True)
class FrozenEnvironment:
    """One immutable source copied for both Owner and Secondary."""

    _entries: tuple[tuple[str, str], ...] = field(repr=False)
    manifest: EnvironmentManifest

    def clone(self) -> dict[str, str]:
        return dict(self._entries)


@dataclass(frozen=True, slots=True)
class ProcessIdentity:
    """Non-path identity facts that must match between both launches."""

    session_id: int
    user_token_sha256: str = field(repr=False)
    integrity_level: str
    desktop: str = field(repr=False)
    window_station: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class LaunchContext:
    """Frozen process inputs shared by Owner and Secondary."""

    environment: FrozenEnvironment
    working_directory: Path
    identity: ProcessIdentity

    def clone_environment(self) -> dict[str, str]:
        return self.environment.clone()


@dataclass(frozen=True, slots=True)
class FrozenLaunchPair:
    """Two independent dictionaries derived from one immutable snapshot."""

    context: LaunchContext
    owner_environment: Mapping[str, str] = field(repr=False)
    secondary_environment: Mapping[str, str] = field(repr=False)


class ProbePhase(StrEnum):
    CREATED = "created"
    OWNER_RUNNING = "owner_running"
    SECONDARY_RUNNING = "secondary_running"
    SECONDARY_EXITED = "secondary_exited"
    OWNER_EXITED = "owner_exited"
    FAILED = "failed"


@dataclass(slots=True)
class ProbeLifecycle:
    """Enforce one Owner, one Secondary, and identity-safe cleanup."""

    phase: ProbePhase = ProbePhase.CREATED
    owner_creation_count: int = 0
    secondary_creation_count: int = 0
    owner_pid: int | None = None
    secondary_pid: int | None = None
    owner_creation_token: str | None = field(default=None, repr=False)
    secondary_creation_token: str | None = field(default=None, repr=False)

    def owner_created(self, pid: int, creation_token: str) -> None:
        if self.phase is not ProbePhase.CREATED or self.owner_creation_count:
            raise ProbeLifecycleError("owner_retry_forbidden")
        _validate_process_identity(pid, creation_token)
        self.owner_creation_count = 1
        self.owner_pid = pid
        self.owner_creation_token = creation_token
        self.phase = ProbePhase.OWNER_RUNNING

    def owner_create_failed(self) -> None:
        if self.phase is not ProbePhase.CREATED:
            raise ProbeLifecycleError("owner_failure_order_invalid")
        self.phase = ProbePhase.FAILED

    def secondary_created(self, pid: int, creation_token: str) -> None:
        if (
            self.phase is not ProbePhase.OWNER_RUNNING
            or self.secondary_creation_count
        ):
            raise ProbeLifecycleError("secondary_retry_or_order_invalid")
        _validate_process_identity(pid, creation_token)
        self.secondary_creation_count = 1
        self.secondary_pid = pid
        self.secondary_creation_token = creation_token
        self.phase = ProbePhase.SECONDARY_RUNNING

    def secondary_exited(self) -> None:
        if self.phase is not ProbePhase.SECONDARY_RUNNING:
            raise ProbeLifecycleError("secondary_exit_order_invalid")
        self.phase = ProbePhase.SECONDARY_EXITED

    def owner_exited(self) -> None:
        if self.phase not in {
            ProbePhase.OWNER_RUNNING,
            ProbePhase.SECONDARY_EXITED,
        }:
            raise ProbeLifecycleError("owner_exit_order_invalid")
        self.phase = ProbePhase.OWNER_EXITED

    def require_exact_secondary(
        self,
        pid: int,
        creation_token: str,
    ) -> None:
        if (
            self.phase is not ProbePhase.SECONDARY_RUNNING
            or pid != self.secondary_pid
            or creation_token != self.secondary_creation_token
        ):
            raise ProbeLifecycleError("secondary_identity_mismatch")


def prepare_launch_pair(
    parent: Mapping[str, str],
    *,
    repository_root: Path,
    runtime_root: Path,
    working_directory: Path,
    identity: ProcessIdentity,
) -> FrozenLaunchPair:
    """Read the parent once and clone the same frozen environment twice."""

    environment = build_canonical_environment(
        dict(parent),
        repository_root=repository_root,
        runtime_root=runtime_root,
    )
    context = LaunchContext(
        environment=environment,
        working_directory=working_directory,
        identity=identity,
    )
    return FrozenLaunchPair(
        context=context,
        owner_environment=MappingProxyType(environment.clone()),
        secondary_environment=MappingProxyType(environment.clone()),
    )


def build_canonical_environment(
    parent: Mapping[str, str],
    *,
    repository_root: Path,
    runtime_root: Path,
) -> FrozenEnvironment:
    """Normalize one parent snapshot without retaining unsafe variables."""

    repository = repository_root.resolve(strict=False)
    runtime = runtime_root.resolve(strict=False)
    if not runtime.is_relative_to(repository) or runtime == repository:
        raise CanonicalEnvironmentError("runtime_root_outside_repository")

    normalized: dict[str, tuple[str, str]] = {}
    duplicate_count = 0
    path_candidates: list[tuple[str, str]] = []
    for name, value in parent.items():
        if not isinstance(name, str) or not isinstance(value, str) or not name:
            raise CanonicalEnvironmentError("environment_entry_invalid")
        folded = name.casefold()
        if folded == "path":
            path_candidates.append((name, value))
            continue
        upper = name.upper()
        if _must_filter(upper):
            continue
        existing = normalized.get(folded)
        if existing is not None:
            duplicate_count += 1
            if existing[1] != value:
                raise CanonicalEnvironmentError(
                    "conflicting_environment_duplicate"
                )
            continue
        normalized[folded] = (name, value)

    if path_candidates:
        duplicate_count += max(0, len(path_candidates) - 1)
        preferred = next(
            (item for item in path_candidates if item[0] == "Path"),
            path_candidates[0],
        )
        normalized["path"] = ("Path", preferred[1])

    redirects = {
        "TEMP": runtime / "temp",
        "TMP": runtime / "temp",
        "TMPDIR": runtime / "temp",
        "APPDATA": runtime / "appdata",
        "LOCALAPPDATA": runtime / "localappdata",
        "HOME": runtime / "userprofile",
        "USERPROFILE": runtime / "userprofile",
    }
    for name, path in redirects.items():
        normalized[name.casefold()] = (name, str(path))

    entries = tuple(
        sorted(normalized.values(), key=lambda item: item[0].casefold())
    )
    manifest = _make_manifest(
        entries,
        duplicate_key_count=duplicate_count,
        redirects=redirects,
        repository_root=repository,
    )
    return FrozenEnvironment(entries, manifest)


def require_matching_launch_contexts(
    owner: LaunchContext,
    secondary: LaunchContext,
) -> None:
    """Fail before Secondary when any namespace or identity input differs."""

    if owner.environment.manifest.aggregate_sha256 != (
        secondary.environment.manifest.aggregate_sha256
    ):
        raise LaunchContextMismatch("environment_manifest_mismatch")
    if owner.working_directory.resolve(strict=False) != (
        secondary.working_directory.resolve(strict=False)
    ):
        raise LaunchContextMismatch("working_directory_mismatch")
    if owner.identity.session_id != secondary.identity.session_id:
        raise LaunchContextMismatch("session_mismatch")
    if owner.identity.user_token_sha256 != secondary.identity.user_token_sha256:
        raise LaunchContextMismatch("user_token_mismatch")
    if owner.identity.integrity_level != secondary.identity.integrity_level:
        raise LaunchContextMismatch("integrity_level_mismatch")
    if owner.identity.desktop != secondary.identity.desktop:
        raise LaunchContextMismatch("desktop_mismatch")
    if owner.identity.window_station != secondary.identity.window_station:
        raise LaunchContextMismatch("window_station_mismatch")


def _must_filter(upper_name: str) -> bool:
    return (
        upper_name in _FILTERED_NAMES
        or upper_name.startswith("QT_")
        or upper_name.startswith("ARKCLAW_")
        or upper_name.endswith("_PROXY")
        or any(marker in upper_name for marker in _SENSITIVE_MARKERS)
    )


def _validate_process_identity(pid: int, creation_token: str) -> None:
    if pid <= 0 or not creation_token:
        raise ProbeLifecycleError("process_identity_invalid")


def _make_manifest(
    entries: tuple[tuple[str, str], ...],
    *,
    duplicate_key_count: int,
    redirects: Mapping[str, Path],
    repository_root: Path,
) -> EnvironmentManifest:
    names = tuple(name for name, _ in entries)
    hashes = {
        name: hashlib.sha256(value.encode("utf-8")).hexdigest()
        for name, value in entries
    }
    outside_count = sum(
        not path.resolve(strict=False).is_relative_to(repository_root)
        for path in redirects.values()
    )
    base = {
        "schema": 1,
        "key_names": list(names),
        "value_sha256": hashes,
        "key_count": len(entries),
        "duplicate_key_count": duplicate_key_count,
        "repository_redirect_count": len(redirects),
        "outside_repository_path_count": outside_count,
        "environment_values_recorded": False,
    }
    payload = json.dumps(
        base,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return EnvironmentManifest(
        key_names=names,
        value_sha256=MappingProxyType(hashes),
        key_count=len(entries),
        duplicate_key_count=duplicate_key_count,
        repository_redirect_count=len(redirects),
        outside_repository_path_count=outside_count,
        aggregate_sha256=hashlib.sha256(payload).hexdigest(),
    )
