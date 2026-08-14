# ArkClaw 交接文档核对与仓库复核

> 日期：2026-08-14
> 依据：`docs/HANDOFF_CURRENT_ARCHITECTURE.md`（交接文档）
> 基线：`D:\ArkClaw\.worktrees\arkpets-spine-idle-vertical-slice` 工作树
> 方法：逐项对照工作树实际文件（git 状态、pyproject、uv.lock、源码类/函数、脚本、原生桥、文档）验证，不修改任何生产文件。

## 1. 核对结论摘要

交接文档与当前工作树现状**高度一致**，可作为主干切换的事实基础。核对范围覆盖：

- 工作树 / 分支 / 提交 / 未提交状态；
- `src/arkclaw/` 包结构与 `src/sjtuclaw/` 删除状态；
- pyproject 四个入口与 uv.lock 包名；
- Spine 3.8 原生桥（CMake、C++17、固定提交、DLL 产物）；
- 启动脚本 `start_schwarz_pet.ps1` 与角色包 manifest schema；
- 七个逻辑动作、Track 0、自动调度、安全降级渲染链；
- 控制中心、右键展开栏、溢出窗口、输入命中；
- 配置 / 凭据 / 自启动的 ArkClaw 命名空间。

发现的差异共 2 项（文档目录树错误、GPL 审计遗漏），均为**文档级问题，不影响代码事实**。

## 2. 逐节核对结果

| 交接文档章节 | 结果 | 证据 |
|---|---|---|
| §2.1 工作树/分支/提交 | ✅ | `.worktrees/arkpets-spine-idle-vertical-slice` @ `4511d32`（`codex/arkpets-spine-idle-vertical-slice`），大量未提交改动 |
| §2.1 `src/sjtuclaw/` 删除、`src/arkclaw/` 新增 | ✅ | git status：`src/sjtuclaw/**` staged 删除；`src/arkclaw/` untracked；代码中已无任何 `sjtuclaw` 引用残留 |
| §4 目录架构 | ⚠️ | 整体一致；**`src/arkclaw/security/` 实际不存在**（见 §3.1） |
| §4.1 分层原则 | ✅ | README「架构约束」：domain/application 不得依赖 PySide6/OpenAI/SQLite/具体 Spine adapter |
| §5 总体运行架构 | ✅ | `ProductionPetComposition`、`Spine38NativeLibrary`、`PetTrack0Controller`、`Spine38PetRenderer`、`OpenGLTexturedMeshBackend`、`AutonomousActionScheduler`、`PetApplicationCoordinator`、fallback 链全部存在 |
| §6 启动顺序 | ✅ | `pet_application.py`：QApplication → SingleInstance → QtRuntimeBridge → MainWindow/ControlCenterView → `create_optional_production_pet_composition` → PetWindow/overlay/tray/coordinator → 失败走 fallback |
| §7.1 PetWindow | ✅ | 透明无边框窗口、tick、输入、布局委托（`pet_window.py`） |
| §7.2 可见区域与溢出 | ✅ | `_PET_WIDTH=160`、`_PET_HEIGHT=180`；`PetEffectOverlayWindow`、`PetSurfaceHitFrame`、`PetPointerGesture` 均存在 |
| §8.1 七个逻辑动作 | ✅ | `ProductionAction`：RELAX/MOVE_LEFT/MOVE_RIGHT/SIT/SLEEP/SPECIAL/INTERACT |
| §8.2 Track 0 播放链 | ✅ | `PetTrack0Controller`、`AnimationRoleRegistry`、`Spine38AnimationPlayer`、`require_schwarz_production()`；`MIRROR_MOVE` 策略（`MoveDirectionPolicy`） |
| §9.1 Native bridge | ✅ | CMake ≥3.25、C++17、`OUTPUT_NAME arkclaw_spine38_bridge`；`spine-runtimes.lock.json` 固定提交 `8b4844bd4b193ba9e54487ed397a777993cbad56`、数据版本 3.8；`build/spine38/Release/arkclaw_spine38_bridge.dll` 已存在 |
| §9.2 Python 渲染链 | ✅ | `Spine38NativeLibrary`/`Spine38Runtime`/`Spine38AnimationPlayer`/`Spine38PetRenderer`/`OpenGLTexturedMeshBackend`/`SafePetRenderer`/`PlaceholderPetRenderer` 全部存在 |
| §10 控制中心/右键展开栏 | ✅ | `ControlCenterView`（Home/My Pets/Animations/Interaction/Appearance/Settings/Inspector）；`ProductionActionMenuSection`；`PetApplicationCoordinator` 统一接线 |
| §11.1 角色包 manifest | ✅ | `start_schwarz_pet.ps1` 生成 schema：`schema_version=1`、`pack_id=schwarz-production`、`spine_version=3.8`、SHA256、`mirror_move`、`foot_baseline=180.0`、`texture_page_count=1`，与文档逐字段一致 |
| §12 Agent/Provider | ✅ | Fake/OpenAI/DeepSeek 实现；Ollama 仅配置层（`ProviderNotImplementedError`） |
| §13 配置/凭据/Windows 集成 | ✅ | `%LOCALAPPDATA%\ArkClaw\provider_profiles.json`；Credential target `ArkClaw/OpenAI/APIKey`、`ArkClaw/Credentials/{id}`；HKCU Run 值名 `ArkClaw`；单实例 `ArkClaw.Pet.SingleInstance.V1` |
| §14.1 依赖 | ✅ | uv.lock 包名 `arkclaw`（editable "."）；lock 版本与文档列出的关键传递依赖一致 |
| §15 入口 | ✅ | `arkclaw-agent-demo` / `arkclaw-gui` / `arkclaw-pet` / `arkclaw-pet-placeholder`（后两者同指向 `pet_application:run`）；`test_project_entry_points.py` 已冻结新入口 |
| §16 构建/启动/验收命令 | ✅ | `start_schwarz_pet.ps1` 支持 `-ValidateOnly` / `-Smoke` / `-Console` / `-AssetRoot`，自动解析工作树与共享 `.venv` 并设置 `PYTHONPATH` |
| §18 保留/删除清单 | ✅ | `PetRenderer`/`SafePetRenderer`/`PlaceholderPetRenderer` 确认保留；`prototypes/placeholder_pet/` 仅入口（README+ps1），未复制渲染实现 |

## 3. 发现的差异

### 3.1 `src/arkclaw/security/` 不存在（文档目录树错误）
- 交接文档 §4 与 `STRUCTURE.md` 都把 `security/` 列为 `src/arkclaw/` 顶层包。
- 实际：`src/arkclaw/` 顶层只有 `application / bootstrap / config / domain / infrastructure / presentation`；安全实现位于 `src/arkclaw/infrastructure/security/`。
- 建议：修正 `HANDOFF_CURRENT_ARCHITECTURE.md` 与 `STRUCTURE.md` 的目录树，删除顶层 `security/` 行。

### 3.2 GPL 迁移审计未列入交接风险（重要遗漏）
- `docs/legal/gpl_migration_audit.md` 显示项目正进行 **GPL-3.0-only 迁移审计**，整体门禁 **BLOCKED（audit in progress）**，并要求：清单全部 PASS/NOT APPLICABLE 前，根 `LICENSE`、README 的 source-license 声明与包元数据（`pyproject.toml` 当前 `license = Proprietary`）必须保持不变。
- 交接文档 §20 风险表只列了「Schwarz 素材分发授权 Unknown」，未提及该审计。
- 影响：主干切换、打包发布与 `pyproject.toml` 元数据修改均受该门禁约束；应作为发布前法律复核项补充进交接文档。

### 3.3 次要：新应用层模块未在文档 §4 展开
- `application/` 实际还包含 `pet_render_layout.py`、`pet_role_calibration.py` 等新模块（§4 只写了「动作、状态、运动、角色包和 Agent 用例」）。属简略而非错误，可不改。

## 4. 与上一轮架构审查（main 上的旧报告）的关系

- 上一轮报告 `docs/engineering/repository-architecture-review.md` 位于 **main**（`8b573dd`），描述的是旧 `src/sjtuclaw/` 架构。
- 本轮确认：产品基线已演进为工作树中的 `src/arkclaw/`，旧报告对**新基线不再适用**，应作为历史记录对待。
- 旧报告识别的结构问题在新基线中的状态：

| 旧问题 | 新基线状态 |
|---|---|
| 命名不一致（ArkClaw/SJTUClaw/sjtuclaw） | ✅ 已基本统一：包/入口/凭据/Run 键均为 `arkclaw`/`ArkClaw`，代码零 `sjtuclaw` 残留 |
| `docs/` 扁平混乱 | ✅ 已重组为 `architecture / pet / rendering / providers / packaging / legal / research / superpowers` |
| `application/` 混装 Agent/Pet/系统集成 | ⚠️ 仍在同一包内平铺，但已出现清晰子域（pet_state/motion/action/role_pack/render_layout/calibration） |
| `presentation/qt/` 多职责平铺 | ⚠️ 仍平铺（新增 control_center、effect_overlay、surface_hit_frame、action_menu），尚未子目录化 |
| `scripts/` 混装测试支撑模块 | ⚠️ 仍存在（`manual_*_verification.py` 被测试 import） |
| `packaging/` 五职责混装 | ⚠️ 未变（打包管线 + 探针/诊断/归档仍同目录） |
| `build/` 一次性临时目录 | ⚠️ 未变 |

- 风险等级变化：由于整包改名（`sjtuclaw → arkclaw`），任何未来的文件移动/重组都变成 **High 风险**（import、pytest、mypy、ruff、入口、spec 全部绑定），且必须在**已提交的新基线**上进行。

## 5. 主干切换前置风险清单

按交接文档 §19/§20 与本次核实结果，切换前必须处理：

1. **未提交改动（最高优先级）**：工作树含大量 staged/unstaged/untracked 改动，其中 `src/arkclaw/` 全量 untracked、`src/sjtuclaw/` 全量 staged 删除、原生桥/测试/文档/uv.lock 均有改动。仅记录 `4511d32` 无法恢复当前状态，必须先把工作树完整提交。
2. **共享 `.venv`**：已由启动脚本 `PYTHONPATH` 规避；主干切换后应重建环境并复测。
3. **GPL 迁移审计 BLOCKED（本次新增）**：发布/打包/元数据修改前需法律复核。
4. **autostart / DPI probe 超时**：交接文档已列为需在目标环境复核的项目，不应误报全绿。
5. **素材授权**：Schwarz 素材在仓库外，分发与授权 Unknown。
6. **旧 SJTUClaw 数据迁移**：已验证新命名空间与旧命名空间不重叠（Credential target、`provider_profiles.json` 路径、Run 键值均为 ArkClaw），旧数据不会自动迁移；是否提供迁移工具 Unknown。

## 6. 结论

- 交接文档事实准确率极高，可作为新 `main` 基线的事实来源。
- 建议修正两处文档（`security/` 目录树、补充 GPL 审计风险）后，按交接文档 §19 顺序执行：先提交工作树 → 验收 → 切换 main → 清理旧包。
- 本报告不执行任何代码或 Git 修改。