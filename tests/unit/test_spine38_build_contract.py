from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BUILD_WRAPPER = PROJECT_ROOT / "scripts" / "build_spine38_bridge.ps1"
POWERSHELL = shutil.which("powershell")
EXPECTED_PINNED_SOURCE_MANIFEST = {
    "repository_url": (
        "https://github.com/EsotericSoftware/spine-runtimes.git"
    ),
    "commit": "8b4844bd4b193ba9e54487ed397a777993cbad56",
    "runtime_data_version": "3.8",
    "license_filename": "LICENSE",
}

FAKE_NATIVE_TOOL = r"""
import json
import os
import shutil
import sys
from pathlib import Path


tool = sys.argv[1]
arguments = sys.argv[2:]
log_path = Path(os.environ["FAKE_TOOL_LOG"])
with log_path.open("a", encoding="utf-8") as log:
    log.write(json.dumps({"tool": tool, "arguments": arguments}) + "\n")


def load_state(repository: Path) -> dict[str, object]:
    return json.loads(
        (repository / ".fake-git-state.json").read_text(encoding="utf-8")
    )


def save_state(repository: Path, state: dict[str, object]) -> None:
    repository.mkdir(parents=True, exist_ok=True)
    (repository / ".git").mkdir(exist_ok=True)
    (repository / ".fake-git-state.json").write_text(
        json.dumps(state),
        encoding="utf-8",
    )


if tool == "git":
    if arguments[:1] == ["-C"]:
        repository = Path(arguments[1])
        command = arguments[2:]
    else:
        repository = Path.cwd()
        command = arguments

    if command[:1] == ["init"]:
        repository = Path(command[-1])
        save_state(
            repository,
            {
                "head": None,
                "detached": False,
                "origin": None,
                "fetch_refspecs": [],
            },
        )
        raise SystemExit(0)

    state = load_state(repository)
    if command[:3] == ["remote", "add", "origin"]:
        state["origin"] = command[3]
        state["fetch_refspecs"] = [
            "+refs/heads/*:refs/remotes/origin/*"
        ]
        save_state(repository, state)
        raise SystemExit(0)
    if command[:3] == ["config", "--unset-all", "remote.origin.fetch"]:
        state["fetch_refspecs"] = []
        save_state(repository, state)
        raise SystemExit(0)
    if command[:1] == ["fetch"]:
        marker_value = os.environ.get("FAKE_GIT_FAIL_FETCH_ONCE")
        if marker_value:
            marker = Path(marker_value)
            if not marker.exists():
                marker.write_text("failed\n", encoding="utf-8")
                print("fake_git_fetch_stderr", file=sys.stderr)
                raise SystemExit(41)
        state["fetched_commit"] = command[-1]
        save_state(repository, state)
        print("fake_git_fetch_stdout")
        print("fake_git_fetch_stderr", file=sys.stderr)
        raise SystemExit(0)
    if command[:2] == ["checkout", "--detach"]:
        state["head"] = os.environ["FAKE_PINNED_COMMIT"]
        state["detached"] = True
        save_state(repository, state)
        (repository / "LICENSE").write_text(
            "Spine Runtimes License Agreement\n",
            encoding="utf-8",
        )
        raise SystemExit(0)
    if command == ["rev-parse", "HEAD"]:
        if state.get("head") is None:
            raise SystemExit(1)
        print(state["head"])
        raise SystemExit(0)
    if command == ["symbolic-ref", "-q", "HEAD"]:
        if state.get("detached"):
            raise SystemExit(1)
        print("refs/heads/main")
        raise SystemExit(0)
    if command == ["remote", "get-url", "origin"]:
        if state.get("origin") is None:
            raise SystemExit(1)
        print(state["origin"])
        raise SystemExit(0)
    if command == ["config", "--get-all", "remote.origin.fetch"]:
        refspecs = state.get("fetch_refspecs", [])
        for refspec in refspecs:
            print(refspec)
        raise SystemExit(0 if refspecs else 1)
    print(f"unsupported fake git arguments: {command!r}", file=sys.stderr)
    raise SystemExit(90)


if tool == "cmake":
    print("fake_cmake_stdout")
    print("fake_cmake_stderr", file=sys.stderr)
    if arguments[:1] == ["--build"]:
        build_root = Path(arguments[1])
        configuration = arguments[arguments.index("--config") + 1]
        cmake_state = json.loads(
            (build_root / ".fake-cmake-state.json").read_text(
                encoding="utf-8"
            )
        )
        output = build_root / configuration
        output.mkdir(parents=True, exist_ok=True)
        (output / "sjtuclaw_spine38_bridge.dll").write_bytes(b"fake dll")
        shutil.copy2(
            Path(cmake_state["source"]) / "LICENSE",
            output / "LICENSE",
        )
        raise SystemExit(0)

    build_root = Path(arguments[arguments.index("-B") + 1])
    source_argument = next(
        argument
        for argument in arguments
        if argument.startswith("-DSPINE_RUNTIMES_SOURCE_DIR=")
    )
    source = source_argument.split("=", 1)[1]
    build_root.mkdir(parents=True, exist_ok=True)
    (build_root / ".fake-cmake-state.json").write_text(
        json.dumps({"source": source}),
        encoding="utf-8",
    )
    raise SystemExit(0)


if tool == "ctest":
    print("fake_ctest_stdout")
    print("fake_ctest_stderr", file=sys.stderr)
    raise SystemExit(int(os.environ.get("FAKE_CTEST_EXIT_CODE", "0")))


raise SystemExit(91)
"""


def run_build_wrapper(*arguments: str) -> subprocess.CompletedProcess[str]:
    assert POWERSHELL is not None
    return subprocess.run(
        [
            POWERSHELL,
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


def create_wrapper_project(parent: Path) -> Path:
    project = parent / "wrapper-project"
    bridge = project / "native" / "spine38_bridge"
    (project / "scripts").mkdir(parents=True)
    shutil.copy2(BUILD_WRAPPER, project / "scripts" / BUILD_WRAPPER.name)
    shutil.copytree(PROJECT_ROOT / "native" / "spine38_bridge", bridge)
    return project


def create_fake_tools(
    parent: Path,
    *,
    include_git: bool = True,
    include_cmake: bool = True,
    include_ctest: bool = False,
) -> tuple[Path, Path]:
    tools = parent / "fake-tools"
    tools.mkdir()
    driver = tools / "fake_native_tool.py"
    driver.write_text(textwrap.dedent(FAKE_NATIVE_TOOL), encoding="utf-8")

    for name, included in (
        ("git", include_git),
        ("cmake", include_cmake),
        ("ctest", include_ctest),
    ):
        if not included:
            continue
        shim = tools / f"{name}.cmd"
        shim.write_text(
            "@echo off\r\n"
            f'"{sys.executable}" "{driver}" {name} %*\r\n'
            "exit /b %ERRORLEVEL%\r\n",
            encoding="utf-8",
        )
    return tools, parent / "fake-tool-log.jsonl"


def run_fixture_wrapper(
    project: Path,
    tools: Path,
    log_path: Path,
    *arguments: str,
    extra_environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    assert POWERSHELL is not None
    environment = os.environ.copy()
    environment.update(
        {
            "PATH": str(tools),
            "FAKE_PINNED_COMMIT": EXPECTED_PINNED_SOURCE_MANIFEST["commit"],
            "FAKE_TOOL_LOG": str(log_path),
        }
    )
    if extra_environment:
        environment.update(extra_environment)
    return subprocess.run(
        [
            POWERSHELL,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(project / "scripts" / BUILD_WRAPPER.name),
            *arguments,
        ],
        cwd=project,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def read_fake_tool_log(log_path: Path) -> list[dict[str, object]]:
    if not log_path.exists():
        return []
    return [
        json.loads(line)
        for line in log_path.read_text(encoding="utf-8").splitlines()
    ]


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


def test_managed_acquisition_fetches_only_the_exact_commit(
    tmp_path: Path,
) -> None:
    project = create_wrapper_project(tmp_path)
    tools, log_path = create_fake_tools(tmp_path)

    completed = run_fixture_wrapper(project, tools, log_path)

    assert completed.returncode == 0, completed.stderr
    source = project / "build" / "spine38" / "source"
    state = json.loads(
        (source / ".fake-git-state.json").read_text(encoding="utf-8")
    )
    assert state == {
        "head": EXPECTED_PINNED_SOURCE_MANIFEST["commit"],
        "detached": True,
        "origin": EXPECTED_PINNED_SOURCE_MANIFEST["repository_url"],
        "fetch_refspecs": [],
        "fetched_commit": EXPECTED_PINNED_SOURCE_MANIFEST["commit"],
    }
    git_calls = [
        entry["arguments"]
        for entry in read_fake_tool_log(log_path)
        if entry["tool"] == "git"
    ]
    assert [
        "fetch",
        "--depth",
        "1",
        "--no-tags",
        "origin",
        EXPECTED_PINNED_SOURCE_MANIFEST["commit"],
    ] in [call[2:] if call[:1] == ["-C"] else call for call in git_calls]
    assert not any("clone" in call for call in git_calls)
    assert not list(source.parent.glob("source.acquire.*"))

    output = source.parent / "Release"
    assert (output / "sjtuclaw_spine38_bridge.dll").is_file()
    assert (output / "LICENSE").read_text(encoding="utf-8") == (
        "Spine Runtimes License Agreement\n"
    )
    assert json.loads(
        (output / "spine38-build-manifest.json").read_text(encoding="utf-8")
    ) == {
        "commit": EXPECTED_PINNED_SOURCE_MANIFEST["commit"],
        "configuration": "Release",
        "architecture": "x64",
        "bridge_abi": 1,
    }

    repeated = run_fixture_wrapper(project, tools, log_path)
    assert repeated.returncode == 0, repeated.stderr
    repeated_git_calls = [
        entry["arguments"]
        for entry in read_fake_tool_log(log_path)
        if entry["tool"] == "git"
    ]
    assert sum("fetch" in call for call in repeated_git_calls) == 1


def test_explicit_nonexistent_source_is_not_created_or_downloaded(
    tmp_path: Path,
) -> None:
    project = create_wrapper_project(tmp_path)
    tools, log_path = create_fake_tools(tmp_path)
    explicit_source = tmp_path / "outside-build" / "spine-runtimes"

    completed = run_fixture_wrapper(
        project,
        tools,
        log_path,
        "-SpineSource",
        str(explicit_source),
    )

    assert completed.returncode == 2
    assert completed.stdout.strip() == "spine38_source_missing"
    assert not explicit_source.exists()
    assert read_fake_tool_log(log_path) == []


def test_failed_managed_fetch_is_cleaned_and_next_run_can_retry(
    tmp_path: Path,
) -> None:
    project = create_wrapper_project(tmp_path)
    tools, log_path = create_fake_tools(tmp_path)
    marker = tmp_path / "fail-fetch-once.marker"
    environment = {"FAKE_GIT_FAIL_FETCH_ONCE": str(marker)}

    failed = run_fixture_wrapper(
        project,
        tools,
        log_path,
        extra_environment=environment,
    )

    managed_root = project / "build" / "spine38"
    assert failed.returncode == 1
    assert failed.stdout.splitlines()[-1] == "spine38_source_fetch_failed"
    assert not (managed_root / "source").exists()
    assert not list(managed_root.glob("source.acquire.*"))

    retried = run_fixture_wrapper(
        project,
        tools,
        log_path,
        extra_environment=environment,
    )

    assert retried.returncode == 0, retried.stderr
    assert (managed_root / "source").is_dir()
    assert not list(managed_root.glob("source.acquire.*"))


def test_missing_git_and_cmake_emit_fixed_failure_codes(tmp_path: Path) -> None:
    git_missing_project = create_wrapper_project(tmp_path / "git-missing")
    no_git, git_missing_log = create_fake_tools(
        tmp_path / "git-missing",
        include_git=False,
    )

    git_missing = run_fixture_wrapper(
        git_missing_project,
        no_git,
        git_missing_log,
    )

    assert git_missing.returncode == 1
    assert git_missing.stdout.strip() == "spine38_git_missing"

    cmake_missing_project = create_wrapper_project(tmp_path / "cmake-missing")
    no_cmake, cmake_missing_log = create_fake_tools(
        tmp_path / "cmake-missing",
        include_cmake=False,
    )

    cmake_missing = run_fixture_wrapper(
        cmake_missing_project,
        no_cmake,
        cmake_missing_log,
    )

    assert cmake_missing.returncode == 1
    assert cmake_missing.stdout.strip() == "spine38_cmake_missing"


def test_successful_native_stdout_and_stderr_remain_visible(
    tmp_path: Path,
) -> None:
    project = create_wrapper_project(tmp_path)
    tools, log_path = create_fake_tools(tmp_path)

    completed = run_fixture_wrapper(project, tools, log_path)

    assert completed.returncode == 0, completed.stderr
    assert "fake_git_fetch_stdout" in completed.stdout
    assert "fake_git_fetch_stderr" in completed.stderr
    assert "fake_cmake_stdout" in completed.stdout
    assert "fake_cmake_stderr" in completed.stderr


def test_run_tests_invokes_ctest_with_selected_configuration(
    tmp_path: Path,
) -> None:
    project = create_wrapper_project(tmp_path)
    tools, log_path = create_fake_tools(tmp_path, include_ctest=True)

    completed = run_fixture_wrapper(
        project,
        tools,
        log_path,
        "-Configuration",
        "Debug",
        "-RunTests",
    )

    assert completed.returncode == 0, completed.stderr
    ctest_calls = [
        entry["arguments"]
        for entry in read_fake_tool_log(log_path)
        if entry["tool"] == "ctest"
    ]
    assert ctest_calls == [
        [
            "--test-dir",
            str(project / "build" / "spine38"),
            "-C",
            "Debug",
            "--output-on-failure",
        ]
    ]
    assert "fake_ctest_stdout" in completed.stdout
    assert "fake_ctest_stderr" in completed.stderr
    assert completed.stdout.splitlines()[-1] == "spine38_build_complete"


def test_run_tests_maps_ctest_failure_to_fixed_code(tmp_path: Path) -> None:
    project = create_wrapper_project(tmp_path)
    tools, log_path = create_fake_tools(tmp_path, include_ctest=True)

    completed = run_fixture_wrapper(
        project,
        tools,
        log_path,
        "-RunTests",
        extra_environment={"FAKE_CTEST_EXIT_CODE": "37"},
    )

    assert completed.returncode == 1
    assert "fake_ctest_stdout" in completed.stdout
    assert "fake_ctest_stderr" in completed.stderr
    assert completed.stdout.splitlines()[-1] == "spine38_test_failed"
    assert "spine38_build_complete" not in completed.stdout


def test_run_tests_reports_missing_ctest_with_fixed_code(tmp_path: Path) -> None:
    project = create_wrapper_project(tmp_path)
    tools, log_path = create_fake_tools(tmp_path)

    completed = run_fixture_wrapper(
        project,
        tools,
        log_path,
        "-RunTests",
    )

    assert completed.returncode == 1
    assert completed.stdout.splitlines()[-1] == "spine38_ctest_missing"
    assert "spine38_build_complete" not in completed.stdout
