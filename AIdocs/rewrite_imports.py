"""P2 import rewrite: move application/presentation modules into subpackages.

Transforms every .py under src/tests/scripts/packaging:
  1. Dotted module tokens:  arkclaw.application.<mod>  ->  arkclaw.application.<group>.<mod>
                            arkclaw.presentation.qt.<mod> -> arkclaw.presentation.qt.<group>.<mod>
     (boundary-safe, module names sorted longest-first)
  2. Direct-submodule imports: from arkclaw.application import X  ->  from arkclaw.application.<group> import X
                            from arkclaw.presentation.qt import X -> from arkclaw.presentation.qt.<group> import X
     (names that stay at qt top-level, e.g. pet_application, remain unchanged)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(r"D:\ArkClaw\.worktrees\arkpets-spine-idle-vertical-slice")
SCOPES = [REPO / "src", REPO / "tests", REPO / "scripts", REPO / "packaging"]

APPLICATION_GROUPS: dict[str, set[str]] = {
    "agent": {"active_turn_coordinator", "agent_loop", "context_manager", "runtime_session_controller"},
    "system": {
        "autostart_eligibility",
        "autostart_operation_journal",
        "autostart_service",
        "provider_profile_repository",
        "provider_profile_service",
        "provider_settings_service",
        "startup_mode",
    },
    "pet": {
        "pet_action_sequence",
        "pet_animation",
        "pet_autonomous_scheduler",
        "pet_external_assets",
        "pet_geometry",
        "pet_mesh_model",
        "pet_motion",
        "pet_production_actions",
        "pet_renderer_model",
        "pet_render_layout",
        "pet_role_calibration",
        "pet_role_pack",
        "pet_role_pack_switch",
        "pet_settings",
        "pet_state",
        "pet_track0",
        "spine38_runtime",
    },
}

QT_GROUPS: dict[str, set[str]] = {
    "pet": {
        "pet_effect_overlay",
        "pet_mesh_opengl_renderer",
        "pet_mesh_spike",
        "pet_renderer",
        "pet_surface_hit_frame",
        "pet_window",
        "spine38_player",
        "spine38_renderer",
    },
    "ui": {
        "autostart_controller",
        "autostart_operation_diagnostics",
        "control_center",
        "main_window",
        "owner_ui_readiness",
        "pet_settings_controller",
        "production_action_menu",
        "provider_settings_dialog",
    },
    "platform": {"runtime_bridge", "runtime_thread", "single_instance", "system_tray"},
}

QT_STAY = {"application", "pet_application"}


def group_for(prefix: str, mod: str) -> str | None:
    groups = APPLICATION_GROUPS if prefix == "arkclaw.application" else QT_GROUPS
    for g, mods in groups.items():
        if mod in mods:
            return g
    return None


def dotted_tokens() -> list[tuple[str, str]]:
    """Return sorted (old_token, new_token) pairs, longest module name first."""
    pairs: list[tuple[str, str]] = []
    for prefix, groups in (("arkclaw.application", APPLICATION_GROUPS), ("arkclaw.presentation.qt", QT_GROUPS)):
        for g, mods in groups.items():
            for mod in mods:
                pairs.append((f"{prefix}.{mod}", f"{prefix}.{g}.{mod}"))
    pairs.sort(key=lambda p: len(p[0]), reverse=True)
    return pairs


TOKEN_PAIRS = dotted_tokens()
TOKEN_RE = re.compile(
    "(?<![A-Za-z0-9_])(" + "|".join(re.escape(old) for old, _ in TOKEN_PAIRS) + ")(?![A-Za-z0-9_])"
)
TOKEN_MAP = {old: new for old, new in TOKEN_PAIRS}

DIRECT_RE = re.compile(r"^(\s*)from (arkclaw\.application|arkclaw\.presentation\.qt) import (.*)$")


def _names_from_body(body: str) -> list[str]:
    tokens = re.split(r"[\s,()]+", body)
    return [t for t in tokens if re.fullmatch(r"[A-Za-z_]\w*", t)]


def rewrite_text(text: str) -> str:
    text = TOKEN_RE.sub(lambda m: TOKEN_MAP[m.group(1)], text)
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        m = DIRECT_RE.match(line.rstrip("\r\n"))
        if not m:
            out.append(line)
            i += 1
            continue
        indent, pkg, body = m.group(1), m.group(2), m.group(3)
        # gather continuation lines until the import list is balanced
        stmt_lines = [line.rstrip("\r\n")]
        j = i
        depth = body.count("(") - body.count(")")
        while depth > 0 and j + 1 < len(lines):
            j += 1
            stmt_lines.append(lines[j].rstrip("\r\n"))
            depth += lines[j].count("(") - lines[j].count(")")
        body = " ".join(stmt_lines[1:]) if len(stmt_lines) > 1 else body
        names = _names_from_body(body)
        # group names by target package
        targets: dict[str, list[str]] = {}
        for name in names:
            g = group_for(pkg, name)
            if g is not None:
                targets.setdefault(f"{pkg}.{g}", []).append(name)
            elif pkg == "arkclaw.presentation.qt" and name in QT_STAY:
                targets.setdefault(pkg, []).append(name)
            else:
                targets.setdefault(pkg, []).append(name)
        # emit in original name order, target order = first appearance
        emitted: list[str] = []
        for name in names:
            g = group_for(pkg, name)
            target = f"{pkg}.{g}" if g is not None else pkg
            if target not in emitted:
                emitted.append(target)
        line_end = "\r\n" if line.endswith("\r\n") else "\n"
        block: list[str] = []
        for target in emitted:
            tnames = targets[target]
            if len(tnames) == 1:
                block.append(f"{indent}from {target} import {tnames[0]}")
            else:
                block.append(f"{indent}from {target} import (")
                for n in tnames:
                    block.append(f"{indent}    {n},")
                block.append(f"{indent})")
        out.extend(l + line_end for l in block)
        i = j + 1
    return "".join(out)


def main() -> int:
    changed: list[Path] = []
    for scope in SCOPES:
        for p in sorted(scope.rglob("*.py")):
            if any(part.startswith("__pycache__") for part in p.parts):
                continue
            original = p.read_text(encoding="utf-8")
            rewritten = rewrite_text(original)
            if rewritten != original:
                p.write_text(rewritten, encoding="utf-8")
                changed.append(p)
    print(f"rewrote {len(changed)} files")
    for p in changed:
        print("  ", p.relative_to(REPO))
    # verification: no old dotted tokens left
    remaining: list[tuple[Path, str]] = []
    for scope in SCOPES:
        for p in sorted(scope.rglob("*.py")):
            if any(part.startswith("__pycache__") for part in p.parts):
                continue
            text = p.read_text(encoding="utf-8")
            for old, _ in TOKEN_PAIRS:
                if re.search(r"(?<![A-Za-z0-9_])" + re.escape(old) + r"(?![A-Za-z0-9_])", text):
                    remaining.append((p, old))
    if remaining:
        print("!! REMAINING OLD TOKENS:")
        for p, old in remaining:
            print("   ", p.relative_to(REPO), old)
        return 1
    print("verification: no old dotted tokens remain")
    return 0


if __name__ == "__main__":
    sys.exit(main())
