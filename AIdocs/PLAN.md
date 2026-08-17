# ArkClaw 项目结构重构 — 工作方案

> 日期：2026-08-14
> 依据：交接文档（docs/HANDOFF_CURRENT_ARCHITECTURE.md）+ 架构审查（main 上 docs/engineering/repository-architecture-review.md，历史记录）
> 执行基线：D:\ArkClaw\.worktrees\arkpets-spine-idle-vertical-slice @ 4511d32 + 未提交工作树（即 ArkClaw 完整实现）

## 0. 约束（最高优先级）
1. 不修改任何代码行为 / 视觉效果 / 动画 / 交互。
2. 只允许：文件移动 + 依赖路径（import / 路径常量 / 配置路径）同步修改。
3. 每个阶段独立提交、独立可回退。
4. 每阶段后运行完整验证：pytest 全套 + ruff + mypy。
5. 严格按交接文档 §19 顺序：先保护基线 → 验证 → 结构整理 → 切换 main → 清理。

## 1. 阶段划分

### P0 — 基线保护（交接 §19.1-19.2）
- 工作树 `git add -A` + 提交：把 src/arkclaw、原生桥改名、docs 重组、测试、uv.lock 全部固化为可恢复提交。
- 目的：当前状态只靠 4511d32 无法恢复，必须先提交。

### P1 — 基线验证（交接 §19.4-19.5）
- 运行 `pytest`（unit=75 / qt=21 / integration=3）、`ruff check src tests scripts packaging`、`mypy`。
- 记录基线结果；若个别已知超时/环境项失败，记录不修。

### P2 — 结构整理（本方案核心）
目标结构：

```
src/arkclaw/application/
├── agent/     # active_turn_coordinator, agent_loop, context_manager, runtime_session_controller
├── pet/       # pet_*, spine38_runtime
└── system/    # autostart_*, provider_*, startup_mode

src/arkclaw/presentation/qt/
├── pet/       # pet_window, pet_renderer, pet_mesh_*, pet_effect_overlay, pet_surface_hit_frame, spine38_*
├── ui/        # main_window, control_center, provider_settings_dialog, pet_settings_controller,
│              # autostart_controller, autostart_operation_diagnostics, owner_ui_readiness, production_action_menu
├── platform/  # single_instance, system_tray, runtime_bridge, runtime_thread
├── application.py      # 入口，保持 qt/ 顶层
└── pet_application.py  # 入口，保持 qt/ 顶层
```

- 依赖方向验证：agent → system；pet 独立；无环。✓
- import 重写：脚本机械化替换 `arkclaw.application.<mod>` / `arkclaw.presentation.qt.<mod>` 为带子包前缀的路径。
- 涉及文件：src（含 __init__.py 惰性导出）、tests（119+58 处引用）、scripts（13 个）、packaging（production_import_smoke.py）。
- pyproject 入口不变（application.py / pet_application.py 不移动）；pysidedeploy.spec 不变（只引用 packaging/pet_entry.py）。

### P3 — 文档修正
- STRUCTURE.md 与 HANDOFF 文档的 `src/arkclaw/security/` 目录树错误 → 修正为 `infrastructure/security/`。
- 补充 GPL 迁移审计风险到交接文档风险表。

### P4 — 主干切换（交接 §19.8-19.11）
- main 的本地 WIP 先 `git stash -u`（含 ARKCLAW_UI_DESIGN_V1.md、control_center 等旧版内容）。
- `git merge --ff-only codex/arkpets-spine-idle-vertical-slice`。
- 切换后 main 即为 ArkClaw 结构；旧 src/sjtuclaw 随提交删除。

### P5 — 终验与记录
- 在 main 上重跑完整验证；更新 AIdocs 执行记录。

## 2. 明确不执行（记录理由）
- packaging/ 工具分离：内部用「裸 import + sys.path」互引（standalone_build → dependency_walker_cache；archive_* → transactional_archive），移动会破坏既有可运行约定；风险>收益。→ 记为未来候选。
- scripts/manual_* 迁 tests/support/：文档/README 引用多，收益低。→ 记为未来候选。
- tests/unit 按子系统分组：纯 churn，收益低。→ 记为未来候选。
- build/ 临时目录治理：gitignored 本地产物，不影响结构清晰度。

## 3. 回退策略
- P0 提交：`git reset --soft HEAD^` 可整体回退。
- P2 每个子包一个提交：`git revert <commit>` 独立回退。
- P4 主干切换：ff-only 是纯快进，`git reset --hard 8b573dd`（切换前 main）可回退；WIP 在 stash 中。

## 4. 执行状态（2026-08-14，P0–P5 全部完成）

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

