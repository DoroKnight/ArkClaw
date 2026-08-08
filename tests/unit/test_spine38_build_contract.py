from __future__ import annotations

import json
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BUILD_WRAPPER = PROJECT_ROOT / "scripts" / "build_spine38_bridge.ps1"
EXPECTED_PINNED_SOURCE_MANIFEST = {
    "repository_url": (
        "https://github.com/EsotericSoftware/spine-runtimes.git"
    ),
    "commit": "8b4844bd4b193ba9e54487ed397a777993cbad56",
    "runtime_data_version": "3.8",
    "license_filename": "LICENSE",
}


def run_build_wrapper(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(BUILD_WRAPPER),
            *arguments,
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def create_one_commit_git_repository(parent: Path) -> Path:
    checkout = parent / "wrong-spine-runtimes"
    checkout.mkdir()
    subprocess.run(["git", "init", "--quiet", str(checkout)], check=True)
    (checkout / "README.md").write_text("not the pinned source\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(checkout), "add", "README.md"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(checkout),
            "-c",
            "user.name=SJTUClaw Test",
            "-c",
            "user.email=sjtuclaw-test@example.invalid",
            "commit",
            "--quiet",
            "-m",
            "test fixture",
        ],
        check=True,
    )
    return checkout


def create_empty_git_repository(parent: Path) -> Path:
    checkout = parent / "empty-spine-runtimes"
    subprocess.run(
        ["git", "init", "--quiet", str(checkout)],
        check=True,
    )
    return checkout


def test_build_wrapper_prints_the_pinned_source_manifest() -> None:
    completed = run_build_wrapper("-PrintSourceManifest")

    assert completed.returncode == 0
    assert json.loads(completed.stdout) == EXPECTED_PINNED_SOURCE_MANIFEST


def test_build_wrapper_rejects_a_checkout_at_the_wrong_commit(
    tmp_path: Path,
) -> None:
    wrong_checkout = create_one_commit_git_repository(tmp_path)

    completed = run_build_wrapper(
        "-ValidateSourceOnly",
        "-SpineSource",
        str(wrong_checkout),
    )

    assert completed.returncode == 2
    assert completed.stdout.strip() == "spine38_source_commit_mismatch"


def test_build_wrapper_rejects_a_checkout_without_a_commit(
    tmp_path: Path,
) -> None:
    empty_checkout = create_empty_git_repository(tmp_path)

    completed = run_build_wrapper(
        "-ValidateSourceOnly",
        "-SpineSource",
        str(empty_checkout),
    )

    assert completed.returncode == 2
    assert completed.stdout.strip() == "spine38_source_commit_mismatch"
