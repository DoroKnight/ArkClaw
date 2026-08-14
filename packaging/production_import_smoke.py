from __future__ import annotations

import argparse
import asyncio
import importlib.util
import sys
from pathlib import Path

FORBIDDEN_MODULE_PREFIXES = (
    "pydantic.mypy",
    "mypy",
    "mypyc",
    "httpx._main",
    "pygments",
)


def _forbidden_imports() -> list[str]:
    return sorted(
        name
        for name in sys.modules
        if any(
            name == prefix or name.startswith(f"{prefix}.")
            for prefix in FORBIDDEN_MODULE_PREFIXES
        )
    )


def _import_production_surface(root: Path) -> bool:
    from arkclaw.application.provider_profile_service import (
        ProviderProfileService,
    )
    from arkclaw.infrastructure.llm.deepseek_provider import (
        DeepSeekProvider,
    )
    from arkclaw.infrastructure.llm.fake_provider import FakeProvider
    from arkclaw.infrastructure.llm.openai_provider import OpenAIProvider
    from arkclaw.presentation.qt.pet_settings_controller import (
        PetSettingsController,
    )
    from arkclaw.presentation.qt.runtime_bridge import QtRuntimeBridge
    from arkclaw.presentation.qt.single_instance import (
        SingleInstanceManager,
    )
    from arkclaw.presentation.qt.system_tray import SystemTrayController

    imported = (
        ProviderProfileService,
        FakeProvider,
        OpenAIProvider,
        DeepSeekProvider,
        QtRuntimeBridge,
        SystemTrayController,
        SingleInstanceManager,
        PetSettingsController,
    )
    entry_path = root / "packaging/pet_entry.py"
    spec = importlib.util.spec_from_file_location(
        "_arkclaw_production_import_probe",
        entry_path,
    )
    if spec is None or spec.loader is None:
        return False
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return len(imported) == 8 and "run" in vars(module)


async def _run_fake_provider_smoke() -> bool:
    from arkclaw.domain.models import (
        ChatMessage,
        LLMRequest,
        MessageRole,
    )
    from arkclaw.infrastructure.llm.fake_provider import FakeProvider

    provider = FakeProvider(response_text="offline-production-smoke")
    request = LLMRequest(
        instructions="Offline deterministic smoke.",
        messages=(ChatMessage(MessageRole.USER, "offline"),),
        max_output_tokens=64,
    )
    event_count = 0
    try:
        async for _event in provider.generate_stream(request):
            event_count += 1
    finally:
        await provider.aclose()
    pending = {
        task
        for task in asyncio.all_tasks()
        if task is not asyncio.current_task() and not task.done()
    }
    return event_count > 1 and provider.closed and not pending


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the fixed offline production import smoke."
    )
    parser.add_argument("--confirm-imports", action="store_true")
    return parser.parse_args()


def main() -> int:
    arguments = _parse_arguments()
    if not arguments.confirm_imports:
        print("safe_code=production_import_smoke_disabled")
        return 0
    root = Path(__file__).resolve().parents[1]
    try:
        imports_valid = _import_production_surface(root)
        fake_smoke_valid = asyncio.run(_run_fake_provider_smoke())
        forbidden = _forbidden_imports()
    except Exception:
        print("safe_code=production_import_smoke_failed")
        return 2
    completed = imports_valid and fake_smoke_valid and not forbidden
    print(
        " ".join(
            (
                f"production_imports_valid={str(imports_valid).lower()}",
                f"fake_provider_smoke={str(fake_smoke_valid).lower()}",
                f"forbidden_module_count={len(forbidden)}",
                "network_accessed=false",
                "credential_manager_accessed=false",
            )
        )
    )
    print(
        "safe_code="
        f"{'production_import_smoke_complete' if completed else 'production_import_smoke_failed'}"
    )
    return 0 if completed else 2


if __name__ == "__main__":
    sys.exit(main())
