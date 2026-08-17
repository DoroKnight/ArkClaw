from pathlib import Path
p = Path(r"D:\ArkClaw\AIdocs\PLAN.md")
raw = p.read_text(encoding="utf-8")
if "## 4. 执行状态" in raw:
    print("already has execution status")
    raise SystemExit(0)
nl = "\r\n" if "\r\n" in raw else "\n"
section = """## 4. 执行状态（2026-08-14，P0–P5 全部完成）

| 阶段 | 实际执行 | 提交 / 结果 |
|---|---|---|
| P0 | 工作树完整实现固化为可恢复提交 | `7a6fb3c`（工作树分支） |
| P1 | 基线验证（pytest/ruff/mypy） | pytest 3053 passed / 10 skipped / 10 failed；ruff 全过；mypy src 0 error |
| P2 | 结构整理：`application/` → `agent/ pet/ system/`；`presentation/qt/` → `pet/ ui/ platform/`；入口留守 qt 顶层；仅同步 import/路径 | `9fc4f04`；回归失败集合与基线完全一致 |
| P3 | 文档同步（STRUCTURE / HANDOFF §4 / 打包预检模块路径）+ GPL 风险行 + HANDOFF infrastructure 子树补全 | `f6e778a` |
| P4 | **偏差**：ff-only 失败（main 与分支在 `71afeae` 分叉，main 独有 `dee6957`、`8b573dd` 两个小提交）；改为 `git stash -u` 后 `git reset --hard f6e778a`，并删除 `src/sjtuclaw` 残留缓存目录 | main @ `f6e778a`（ahead 64 / behind 2，未推送） |
| P5 | 在 main 上重跑完整验证 | pytest 3057 / 10 / 6（失败为基线 10 个失败的精确实集）；ruff 全过；mypy src 0 error；`-ValidateOnly` 通过；`-Smoke` 8/8 通过 |

- 旧 main 独有提交内容：`dee6957` 仅 `.claude/settings.local.json`；`8b573dd` 仅 `.gitignore` +1 行与验收修复设计文档（该文档与分支 blob 完全相同）。均可通过 reflog 找回。
- main 旧版 WIP（`ARKCLAW_UI_DESIGN_V1.md`、`control_center.py`、`test_control_center_ui.py`、sjtuclaw 窗口修改）保留在 `git stash`，未并入新基线。
- 回退策略修正：P4 回退 = `git reset --hard 8b573dd`（旧 main 提交仍在 reflog；WIP 在 stash）。
- 详细执行记录见 `docs/engineering/repository-architecture-review.md` §17。
"""
out = raw.rstrip() + nl + nl + section + nl
p.write_text(out, encoding="utf-8")
print("PLAN.md execution status appended")