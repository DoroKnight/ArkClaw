from __future__ import annotations

import argparse
import contextlib
import importlib.metadata as importlib_metadata
import importlib.util
import json
import os
import sys
import uuid
from pathlib import Path

INVENTORY_RELATIVE_PATH = Path(
    "build/windows-packaging-environment/environment_inventory.json"
)
REQUIRED_DISTRIBUTIONS = {
    "nuitka": "4.0",
    "openai": "2.48.0",
    "pyside6": "6.11.1",
    "sjtuclaw": "0.1.0",
}
REQUIRED_IMPORTS = (
    "sjtuclaw",
    "openai",
    "PySide6",
    "nuitka",
    "httpx",
    "pydantic",
)
FORBIDDEN_NAMES = (
    "mypy",
    "mypy_extensions",
    "mypyc",
    "pytest",
    "pygments",
    "ruff",
)


def _normalized(name: str) -> str:
    return name.casefold().replace("-", "_")


def _atomic_write(path: Path, payload: object) -> bool:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.part")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with temporary.open("xb") as stream:
            stream.write(
                (
                    json.dumps(
                        payload,
                        ensure_ascii=True,
                        indent=2,
                        sort_keys=True,
                    )
                    + "\n"
                ).encode("utf-8")
            )
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        return True
    except OSError:
        return False
    finally:
        with contextlib.suppress(OSError):
            temporary.unlink(missing_ok=True)


def inventory(repository_root: Path) -> tuple[bool, dict[str, object]]:
    root = repository_root.resolve(strict=True)
    environment = (root / ".venv-packaging").resolve(strict=True)
    development_site = (
        root / ".venv/Lib/site-packages"
    ).resolve(strict=False)
    site_packages = (
        environment / "Lib/site-packages"
    ).resolve(strict=True)
    distributions = {
        _normalized(distribution.metadata["Name"]): distribution.version
        for distribution in importlib_metadata.distributions()
        if distribution.metadata["Name"]
    }
    required_versions_valid = all(
        distributions.get(name) == version
        for name, version in REQUIRED_DISTRIBUTIONS.items()
    )
    forbidden_distributions = sorted(
        name
        for name in FORBIDDEN_NAMES
        if _normalized(name) in distributions
    )
    forbidden_specs = sorted(
        name
        for name in FORBIDDEN_NAMES
        if importlib.util.find_spec(name) is not None
    )
    required_specs_valid = all(
        importlib.util.find_spec(name) is not None
        for name in REQUIRED_IMPORTS
    )
    filesystem_names = {
        _normalized(path.name.split(".", 1)[0])
        for path in site_packages.iterdir()
    }
    forbidden_filesystem = sorted(
        name
        for name in FORBIDDEN_NAMES
        if _normalized(name) in filesystem_names
    )
    sys_paths = tuple(
        Path(value).resolve(strict=False) for value in sys.path if value
    )
    prefix_valid = Path(sys.prefix).resolve(strict=True) == environment
    base_prefix_valid = (
        Path(sys.base_prefix).resolve(strict=True)
        != (root / ".venv").resolve(strict=False)
    )
    virtual_environment_valid = (
        Path(os.environ.get("VIRTUAL_ENV", "")).resolve(strict=False)
        == environment
    )
    pythonpath_clean = not os.environ.get("PYTHONPATH")
    development_site_absent = development_site not in sys_paths
    valid = all(
        (
            sys.version_info[:3] == (3, 13, 6),
            sys.maxsize > 2**32,
            prefix_valid,
            base_prefix_valid,
            virtual_environment_valid,
            pythonpath_clean,
            development_site_absent,
            required_versions_valid,
            required_specs_valid,
            not forbidden_distributions,
            not forbidden_specs,
            not forbidden_filesystem,
        )
    )
    return valid, {
        "schema_version": 1,
        "packaging_environment_valid": valid,
        "python_version": ".".join(
            str(value) for value in sys.version_info[:3]
        ),
        "amd64": sys.maxsize > 2**32,
        "msc_v_1944": "MSC v.1944" in sys.version,
        "prefix_valid": prefix_valid,
        "base_prefix_valid": base_prefix_valid,
        "virtual_environment_valid": virtual_environment_valid,
        "pythonpath_clean": pythonpath_clean,
        "development_site_absent": development_site_absent,
        "required_versions_valid": required_versions_valid,
        "required_specs_valid": required_specs_valid,
        "forbidden_distributions": forbidden_distributions,
        "forbidden_specs": forbidden_specs,
        "forbidden_filesystem_entries": forbidden_filesystem,
        "distributions": dict(sorted(distributions.items())),
        "environment_values_recorded": False,
    }


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate the fixed production packaging environment."
    )
    parser.add_argument("--write-inventory", action="store_true")
    return parser.parse_args()


def main() -> int:
    arguments = _parse_arguments()
    if not arguments.write_inventory:
        print("safe_code=packaging_environment_inventory_disabled")
        return 0
    root = Path(__file__).resolve().parents[1]
    try:
        valid, report = inventory(root)
    except Exception:
        print("safe_code=packaging_environment_invalid")
        return 2
    if not _atomic_write(root / INVENTORY_RELATIVE_PATH, report):
        print("safe_code=packaging_environment_invalid")
        return 2
    distribution_inventory = report.get("distributions")
    distribution_count = (
        len(distribution_inventory)
        if isinstance(distribution_inventory, dict)
        else 0
    )
    print(
        "packaging_environment_valid="
        f"{str(valid).lower()} "
        f"distribution_count={distribution_count}"
    )
    print(
        "safe_code="
        f"{'packaging_environment_ready' if valid else 'packaging_environment_invalid'}"
    )
    return 0 if valid else 2


if __name__ == "__main__":
    sys.exit(main())
