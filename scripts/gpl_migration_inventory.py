"""Build a deterministic, non-secret repository inventory for GPL auditing."""

from __future__ import annotations

import argparse
import json
import subprocess
import tomllib
from collections.abc import Iterator, Sequence
from pathlib import Path, PurePosixPath
from typing import Any, TypedDict, cast

_CODE_EXTENSIONS = frozenset(
    {
        ".bat",
        ".c",
        ".cc",
        ".cmd",
        ".cpp",
        ".h",
        ".hpp",
        ".java",
        ".ps1",
        ".py",
        ".pyi",
        ".sh",
    }
)
_ASSET_EXTENSIONS: dict[str, frozenset[str]] = {
    "animation": frozenset({".atlas", ".json", ".skel", ".spine"}),
    "audio": frozenset({".flac", ".m4a", ".mp3", ".ogg", ".wav"}),
    "binary": frozenset({".dll", ".dylib", ".exe", ".pyd", ".so"}),
    "font": frozenset({".eot", ".otf", ".ttf", ".woff", ".woff2"}),
    "image": frozenset({".bmp", ".gif", ".ico", ".jpeg", ".jpg", ".png", ".svg", ".webp"}),
    "model": frozenset({".fbx", ".glb", ".gltf", ".obj", ".stl"}),
}


class LockedDependency(TypedDict):
    """One resolved package from the lock file."""

    name: str
    version: str


class DependencyInventory(TypedDict):
    """Declared and locked dependency groups."""

    direct: list[str]
    optional: dict[str, list[str]]
    build: list[str]
    packaging: list[str]
    locked: list[LockedDependency]


type AssetInventory = dict[str, list[str]]


class GitInventory(TypedDict):
    """Minimal non-secret Git history summary."""

    commit_count: int
    contributors: list[str]


class RepositoryInventory(TypedDict):
    """Stable JSON-compatible audit inventory."""

    code_files: list[str]
    dependencies: DependencyInventory
    assets: AssetInventory
    native_runtime_files: list[str]
    git: GitInventory


def _run_git(repo_root: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return completed.stdout


def _relative_posix_path(value: str) -> str:
    normalized = PurePosixPath(value.replace("\\", "/"))
    if normalized.is_absolute() or ".." in normalized.parts:
        raise ValueError(f"inventory path must be repository-relative: {value!r}")
    return normalized.as_posix()


def _tracked_files(repo_root: Path) -> list[str]:
    output = _run_git(repo_root, "ls-files", "-z")
    return sorted(
        _relative_posix_path(value)
        for value in output.split("\0")
        if value
    )


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return []
    return sorted(cast(list[str], value))


def _dependency_inventory(repo_root: Path) -> DependencyInventory:
    with (repo_root / "pyproject.toml").open("rb") as stream:
        project_data = tomllib.load(stream)
    build_system = cast(dict[str, Any], project_data.get("build-system", {}))
    project = cast(dict[str, Any], project_data.get("project", {}))
    optional_raw = cast(dict[str, object], project.get("optional-dependencies", {}))
    optional = {
        group: _string_list(requirements)
        for group, requirements in sorted(optional_raw.items())
    }

    locked: list[LockedDependency] = []
    lock_path = repo_root / "uv.lock"
    if lock_path.exists():
        with lock_path.open("rb") as stream:
            lock_data = tomllib.load(stream)
        package_rows = cast(list[dict[str, object]], lock_data.get("package", []))
        for row in package_rows:
            name = row.get("name")
            version = row.get("version")
            if isinstance(name, str) and isinstance(version, str):
                locked.append({"name": name, "version": version})
    locked.sort(key=lambda item: (item["name"].casefold(), item["version"]))

    return {
        "direct": _string_list(project.get("dependencies", [])),
        "optional": optional,
        "build": _string_list(build_system.get("requires", [])),
        "packaging": optional.get("packaging", []),
        "locked": locked,
    }


def _asset_inventory(tracked_files: Sequence[str]) -> AssetInventory:
    assets: AssetInventory = {
        "animation": [],
        "audio": [],
        "binary": [],
        "font": [],
        "image": [],
        "model": [],
    }
    for relative_path in tracked_files:
        suffix = PurePosixPath(relative_path).suffix.casefold()
        for category, extensions in _ASSET_EXTENSIONS.items():
            if suffix in extensions:
                assets[category].append(relative_path)
                break
    return assets


def _git_inventory(repo_root: Path) -> GitInventory:
    count_text = _run_git(repo_root, "rev-list", "--count", "HEAD").strip()
    contributor_lines = _run_git(repo_root, "log", "--format=%aN <%aE>").splitlines()
    return {
        "commit_count": int(count_text),
        "contributors": sorted(set(contributor_lines), key=str.casefold),
    }


def build_inventory(repo_root: Path) -> RepositoryInventory:
    """Return a deterministic inventory for the Git repository at *repo_root*."""

    root = repo_root.resolve(strict=True)
    tracked_files = _tracked_files(root)
    assets = _asset_inventory(tracked_files)
    return {
        "code_files": [
            path
            for path in tracked_files
            if PurePosixPath(path).suffix.casefold() in _CODE_EXTENSIONS
        ],
        "dependencies": _dependency_inventory(root),
        "assets": assets,
        "native_runtime_files": list(assets["binary"]),
        "git": _git_inventory(root),
    }


def iter_inventory_paths(inventory: RepositoryInventory) -> Iterator[str]:
    """Yield every path stored in an inventory for path-safety assertions."""

    yield from inventory["code_files"]
    yield from inventory["native_runtime_files"]
    for paths in inventory["assets"].values():
        yield from paths


def _parse_args(arguments: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path)
    return parser.parse_args(arguments)


def main(arguments: Sequence[str] | None = None) -> int:
    """Render the inventory as stable JSON, optionally to an output file."""

    options = _parse_args(arguments)
    rendered = json.dumps(
        build_inventory(options.repo),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    if options.output is None:
        print(rendered)
    else:
        options.output.write_text(f"{rendered}\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
