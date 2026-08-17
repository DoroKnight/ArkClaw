# ArkClaw Repository Architecture Review

> 阶段：Repository Architecture Audit & File Organization Review（审查与规划，不执行迁移）
> 日期：2026-08-14
> 原则：`Correctness > Stability > Clarity > Architectural Purity`
> 本阶段只新增本文件，不修改任何生产代码，不移动任何核心源文件。
>
> **状态更新（2026-08-14，结构整理已执行）**：本文件正文（§1–§16）为**重构前审计快照**，
> 描述 `src/sjtuclaw/` 时代的仓库事实。审计后的结构整理已执行完毕并通过回归验证，
> 当前仓库结构、迁移记录与验证结果见 **§17 Post-Refactor Execution Record**。

---

## 1. Executive Summary

ArkClaw 仓库（Git 项目名 SJTUClaw，产品二进制名 `SJTUClaw.exe`）当前是一个
**分层清晰的 Python 桌面 AI 桌宠项目**：

- 生产代码全部位于 `src/sjtuclaw/`，已按 `domain / application / infrastructure /
  presentation / config / bootstrap` 六层组织，并且 README 明确记录了
  “`domain` 与 `application` 不得依赖 PySide6 / OpenAI / SQLite” 的架构约束。
- Agent Runtime（`AgentLoop`、`RuntimeSessionController`、Provider 体系）与
  Desktop Pet（`pet_state/motion/animation/renderer_model` + `PetWindow`）都已经
  实现为框架无关的核心 + Qt 适配的形态，测试覆盖充分（68 个测试文件，
  `tests/unit|qt|integration` 已分层）。
- 尚未实现的 Spine Runtime 以“外部资源契约”形式存在
  （`pet_external_assets.py` + `pet_renderer_model.py` 的 Spine 3.8 描述符与
  SHA-256 校验边界），当前可见角色渲染是程序化 `PlaceholderPetRenderer`
  （QPainter 绘制的占位角色）。
- 主要结构问题不在 `src/` 内部，而在仓库外围：`application/` 与
  `presentation/qt/` 各自承担了多个子系统职责；`scripts/`、`packaging/`、
  `docs/` 是“职责混装”的三大扁平目录；`build/` 被大量一次性诊断脚本当作
  临时工作区使用；产品命名（ArkClaw / SJTUClaw / sjtuclaw）不统一。

结论：**当前 src 分层是健康的，不需要“为漂亮而重构”；真正的整理空间在
外围目录（docs / scripts / packaging / build）以及未来 Spine Runtime 落地时的
子系统拆分。** 任何 `src/` 内部重组都属于高风险迁移，必须独立成阶段并保留
完整行为基线。

---

## 2. Current Repository Tree

以下为审计时（重构前）的目录树快照（折叠生成物与缓存；`build/`、`dist/`、
`packaging/deployment/` 为生成物，见 §3）。

```text
ArkClaw/                                  # 仓库根（产品二进制名 SJTUClaw）
├── README.md                             # 产品与架构约束文档（含层依赖规则）
├── pyproject.toml                        # setuptools + pytest/ruff/mypy + 3 个入口点
├── uv.lock                               # 锁定依赖
├── .env.example                          # 非敏感开发环境变量样例
├── .gitignore
├── ARKCLAW_UI_DESIGN_V1.md               # UI 设计提案（新加入，尚未归入 docs/）
│
├── src/sjtuclaw/                         # 唯一生产包
│   ├── __init__.py
│   ├── __main__.py                       # CLI：sjtuclaw-agent-demo 入口（Agent 演示）
│   ├── bootstrap/                        # 组合根
│   │   ├── qt_runtime.py                 #   Production/Fake Qt 组合根（依赖图装配）
│   │   ├── autostart.py                  #   生产 autostart 服务构造
│   │   └── autostart_diagnostics.py      #   自启动运行时诊断（无副作用）
│   ├── config/                           # 非敏感运行时配置 + 凭据边界
│   │   ├── models.py / defaults.py       #   RuntimeConfig 不可变模型
│   │   ├── loader.py / errors.py         #   优先级合并：CLI > env > app > 默认
│   │   ├── secrets.py                    #   SecretStore 抽象 + SecretValue
│   │   ├── provider_profiles.py          #   内置 Provider 档案（OpenAI/DeepSeek/Fake/Ollama）
│   │   └── provider_profile_policy.py    #   Provider 档案封闭策略
│   ├── domain/                           # 框架无关领域层（禁止依赖 Qt/SDK）
│   │   ├── models.py                     #   ProfileId/CredentialId/ProviderProfile/ToolSpec…
│   │   ├── ports.py                      #   LLMProvider/MemoryRepository/Tool/ToolPolicy/SchedulerService
│   │   ├── events.py                     #   LLMEvent / AgentEvent
│   │   ├── errors.py / policies.py       #   领域异常 + DefaultToolPolicy
│   ├── application/                      # 用例/服务层（混装三个子系统，见 §6.1）
│   │   ├── agent_loop.py                 #   Agent 回合事件流
│   │   ├── active_turn_coordinator.py    #   单活跃回合协调
│   │   ├── context_manager.py            #   上下文预算
│   │   ├── runtime_session_controller.py #   Qt 侧单会话运行时所有权
│   │   ├── provider_profile_service.py   #   Provider 生命周期/激活
│   │   ├── provider_settings_service.py  #   Provider 设置边界
│   │   ├── provider_profile_repository.py#   Profile 仓储端口
│   │   ├── autostart_service.py / autostart_eligibility.py /
│   │   │   autostart_operation_journal.py / startup_mode.py
│   │   ├── pet_state.py                  #   分层状态机（lifecycle/motion/behaviors/facing）
│   │   ├── pet_motion.py                 #   运动模型（重力/行走/拖拽/落地/工作区约束）
│   │   ├── pet_animation.py              #   动画意图与调度（delta-time）
│   │   ├── pet_geometry.py               #   Point/Rect/Size（框架无关几何）
│   │   ├── pet_renderer_model.py         #   渲染动作请求 + Spine 3.8 外部资源契约
│   │   ├── pet_mesh_model.py             #   网格模型
│   │   ├── pet_settings.py               #   桌宠设置模型 + 仓储端口
│   │   └── pet_external_assets.py        #   外部资产只读边界（哈希/类型校验）
│   ├── infrastructure/                   # 适配器层
│   │   ├── llm/                          #   openai/deepseek provider + SDK + fake + factory/registry
│   │   ├── config/                       #   JsonPetSettingsRepository / JsonProviderProfileRepository
│   │   ├── autostart/windows_run_key.py  #   HKCU Run 键后端
│   │   ├── security/windows_credential_store.py  # Windows Credential Manager
│   │   └── pet_external_asset_filesystem.py      # Win32 no-follow 文件句柄后端
│   └── presentation/qt/                  # 全部 Qt（混装 Pet / UI Shell / Bridge，见 §6.2）
│       ├── application.py                #   sjtuclaw-gui 入口
│       ├── pet_application.py            #   sjtuclaw-pet-placeholder 入口 + 协调器
│       ├── main_window.py                #   主窗口 Shell（含 WIP 修改）
│       ├── control_center.py             #   ArkClaw v1 控制中心（未提交 WIP）
│       ├── provider_settings_dialog.py   #   Provider 设置对话框
│       ├── pet_window.py                 #   透明无边框桌宠窗口 + 输入 + 右键菜单
│       ├── pet_renderer.py               #   PetRenderer 协议 + SafePetRenderer + Placeholder
│       ├── pet_mesh_opengl_renderer.py   #   OpenGL 纹理网格后端
│       ├── pet_mesh_spike.py             #   软件/离屏 OpenGL 网格 spike
│       ├── runtime_bridge.py             #   Qt 安全命令桥
│       ├── runtime_thread.py             #   QThread + asyncio 运行时 worker
│       ├── autostart_controller.py / autostart_operation_diagnostics.py
│       ├── owner_ui_readiness.py         #   启动就绪诊断
│       ├── pet_settings_controller.py    #   桌宠设置 UI 控制器
│       ├── single_instance.py            #   单实例（QLocalServer）
│       └── system_tray.py                #   系统托盘
│
├── tests/
│   ├── conftest.py                       # 全局禁止非回环网络
│   ├── fakes/                            # fake SDK（openai/deepseek）
│   ├── unit/                             # 51 个单元测试
│   ├── qt/                               # 15 个 Qt 测试（offscreen）+ 1 个子进程辅助
│   └── integration/                      # 2 个集成测试
│
├── scripts/                              # 便利入口 + smoke + 手动验证（混合，见 §6.3）
│   ├── run_qt_app.py / run_pet_placeholder.py / run_agent_demo.ps1
│   ├── test.ps1 / typecheck.ps1
│   ├── qt_gui_smoke.py / qt_pet_smoke.py / qt_runtime_smoke.py /
│   │   qt_tray_smoke.py / qt_single_instance_smoke.py / qt_autostart_smoke.py /
│   │   qt_pet_settings_smoke.py / qt_pet_mesh_spike.py / qt_pet_opengl_backend_smoke.py /
│   │   qt_autostart_layout_probe.py
│   └── manual_credential_targets.py / manual_openai_verification.py /
│       manual_deepseek_verification.py   # 被测试套件 import（测试支撑模块）
│
├── packaging/                            # Nuitka 打包管线 + 探针工具（混合，见 §6.4）
│   ├── pet_entry.py                      # 打包版桌宠入口
│   ├── pysidedeploy.spec                 # Nuitka spec（打包入口/模块清单）
│   ├── build_standalone.ps1              # 独立构建主脚本
│   ├── prepare_packaging_environment.ps1
│   ├── standalone_build.py / standalone_artifact_audit.py / production_import_smoke.py
│   ├── packaging_environment_inventory.py
│   ├── transactional_archive.py / archive_standalone_attempt.py / archive_autostart_rebuild.py
│   ├── dependency_walker_{cache,binary_audit,quarantine,smoke}.py
│   │   dependency_walker_probe.c / dependency_walker_probe_dependency.c
│   │   acquire/audit/build/run/stage_dependency_walker*.ps1
│   ├── autostart_run_timeline_probe.py
│   ├── startup_secondary_environment.py / startup_secondary_probe.py
│   ├── windows_process_exit_observer.py
│   └── packaged_runtime_{supervisor_model,network_observer}.py
│       packaged_runtime_network_supervisor.ps1 / packaged_runtime_dummy_child.ps1
│
├── docs/
│   ├── *.md                              # 14 个扁平工程文档（configuration / providers / pet_* / qt_* / system_tray / single_instance / windows_*）
│   ├── research/                         # 开源 Spine 桌宠调研
│   └── superpowers/
│       ├── plans/                        # Spine 动画生产 / 垂直切片实施计划
│       └── specs/                        # Spine 运行时集成 / 动作复用 / 验收修复设计
│
├── build/                                # 生成物 + 大量一次性诊断临时目录（见 §6.5）
├── dist/SJTUClaw.dist/                   # 生成物：最终独立发行目录（约 133 MB）
├── packaging/deployment/                 # 生成物：Nuitka 中间输出（约 720 MB）
├── .venv/ / .venv-packaging/             # 开发/打包虚拟环境（gitignored）
├── .worktrees/                           # 特性分支独立工作树（gitignored）
└── *.egg-info/ + __pycache__/ + .mypy_cache/ + .pytest_cache/ + .ruff_cache/
```

> 备注：仓库中存在未提交的 WIP（`git status`）：
> `A ARKCLAW_UI_DESIGN_V1.md`、`M main_window.py`、`M pet_application.py`、
> `?? control_center.py`、`?? tests/qt/test_control_center_ui.py`。
> 审查基线是“当前工作树”，因此 `control_center.py` 被视为当前结构的一部分。
---

## 3. Repository Responsibility Map

### 3.1 生产包 `src/sjtuclaw/` 内部职责

| 包 | 实际职责 | 关键文件 |
|---|---|---|
| `domain/` | 框架无关领域模型、端口与事件（禁止依赖 PySide6 / OpenAI / SQLite） | `models.py` / `ports.py` / `events.py` / `errors.py` / `policies.py` |
| `application/` | 用例与编排层。**实际混装三个子系统**：Agent、Desktop Pet、系统集成（autostart / provider / startup），见 §6.1 | `agent_loop.py` / `pet_state.py` / `pet_motion.py` / `pet_animation.py` / `autostart_service.py` / `provider_profile_service.py` / `startup_mode.py` |
| `infrastructure/` | 适配器实现：LLM SDK、凭据、JSON 持久化、Windows Run Key、外部资源文件系统 | `llm/*` / `security/windows_credential_store.py` / `config/*` / `autostart/windows_run_key.py` / `pet_external_asset_filesystem.py` |
| `config/` | 运行时配置模型、加载优先级、SecretStore 边界、Provider 档案 | `models.py` / `loader.py` / `secrets.py` / `provider_profiles.py` / `provider_profile_policy.py` |
| `presentation/qt/` | Qt 表现层：主窗口、桌宠窗口、渲染器、托盘、单实例、runtime 桥 | `application.py` / `pet_window.py` / `pet_renderer.py` / `pet_mesh_opengl_renderer.py` / `system_tray.py` / `runtime_bridge.py` / `runtime_thread.py` / `single_instance.py` |
| `bootstrap/` | 组合根：装配依赖图、构造 autostart 服务 | `qt_runtime.py` / `autostart.py` / `autostart_diagnostics.py` |

### 3.2 仓库外围目录职责

| 目录 | 实际职责 | 备注 |
|---|---|---|
| `tests/` | 测试体系：`unit`（51）/ `qt`（15）/ `integration`（2）+ `fakes/` + 全局防网络 `conftest.py` | 分层清晰，唯一“干净”的外围目录 |
| `scripts/` | 便捷入口（`run_*.py`、`*.ps1`）+ smoke 脚本 + **被测试套件 import 的支撑模块**（`manual_*_verification.py`） | 三类职责混装，见 §6.3 |
| `packaging/` | Nuitka 打包管线（`pet_entry.py` / `pysidedeploy.spec` / `build_standalone.ps1`）+ 打包环境诊断 + 依赖 walker + 运行时探针 + 归档工具 | 五种职责混装，见 §6.4 |
| `docs/` | 工程文档（14 篇扁平 `*.md`）+ `research/`（开源桌宠调研）+ `superpowers/{plans,specs}`（Spine 设计） | 分类与命名不统一，见 §6.6 |
| `build/` | 生成物 + 约 200 个一次性诊断临时目录（autostart / smoke / temp / test-temp / uv-* 前缀） | 临时区，见 §6.5 |
| `dist/SJTUClaw.dist/` | 生成物：最终独立发行目录（约 133 MB） | gitignored |
| `packaging/deployment/` | 生成物：Nuitka 中间输出（约 720 MB） | gitignored |
| `.venv/` / `.venv-packaging/` / `.worktrees/` | 开发 / 打包虚拟环境与工作树 | gitignored |

### 3.3 命名空间归属

- Git 项目名：**SJTUClaw**；Python 包：**`sjtuclaw`**；产品二进制：**`SJTUClaw.exe`**。
- 仓库目录名与若干文档 / 新 UI 文件使用 **ArkClaw**（`ARKCLAW_UI_DESIGN_V1.md`、本报告）。
- 三套命名并行存在，属于命名一致性风险，见 §6.7。

---

## 4. Current Architecture

### 4.1 分层模型（真实，非假设）

当前是一个**六层结构**，依赖方向自上而下，且有一道被 README 与测试双重约束的架构红线：

```text
presentation/qt ──▶ bootstrap ──▶ application ──▶ domain
     │                                    │            ▲
     │                                    └────────────┤
     └──────────────▶ infrastructure ◀─────────────────┘
                          （llm / security / config / autostart / 外部资源）
config 层横向服务于 bootstrap / application / presentation
```

- 架构红线：**`domain` 与 `application` 不得 import PySide6、OpenAI、Ollama、SQLite**（README「架构约束」一节明确记载；`tests/unit/test_provider_architecture.py` 强制执行）。本次审查验证当前代码符合该约束。
- `infrastructure` 是唯一被允许接触 SDK / Windows API / 文件系统的适配层；`config/secrets.py` 提供 `SecretStore` 抽象，Windows 凭据实现在 `infrastructure/security/`。

### 4.2 组合根（Composition Roots）

存在三个生产组合根 + 一个打包组合根：

1. `bootstrap/qt_runtime.py` — 核心装配点：构造 `RuntimeConfig`、Provider 体系、Agent 服务，并产出 Qt 侧 `RuntimeThread` / `RuntimeBridge` 所需对象（Production / Fake 两模式）。
2. `bootstrap/autostart.py` + `autostart_diagnostics.py` — autostart 服务组合根（诊断模式无副作用）。
3. `presentation/qt/pet_application.py` — 桌宠入口的协调器（`run()` 安装 GUI launcher）。
4. `packaging/pet_entry.py` — Nuitka 打包版入口，被 `pysidedeploy.spec` 引用。

### 4.3 两条主运行时管线

**Agent 管线**（框架无关核心 + Qt 适配）：

```text
sjtuclaw-gui / __main__.py
  → bootstrap/qt_runtime.py            （装配）
  → runtime_thread.py (QThread+asyncio) ──▶ runtime_bridge.py (安全命令桥)
  → runtime_session_controller.py      （单会话运行时所有权）
  → agent_loop.py + context_manager.py + active_turn_coordinator.py
  → domain ports (LLMProvider / ToolPolicy / MemoryRepository)
  → infrastructure/llm/*               （openai / deepseek / fake）
  → infrastructure/security/*          （Windows Credential Manager）
```

**桌宠管线**（协议化渲染 + Qt 适配）：

```text
sjtuclaw-pet-placeholder / packaging/pet_entry.py
  → pet_application.py
  → pet_window.py                      （透明无边框窗口 + 输入 + 右键菜单）
  → pet_renderer.py                    （PetRenderer 协议 + SafePetRenderer 所有权）
  → PlaceholderPetRenderer (QPainter) / pet_mesh_opengl_renderer.py（OpenGL 纹理网格后端）
  → application/pet_state|motion|animation|geometry|mesh_model|renderer_model
  → infrastructure/pet_external_asset_filesystem.py  （外部 Spine 3.8 资源契约）
  → presentation/qt/single_instance.py + system_tray.py
```

### 4.4 Spine 状态

- `application/pet_renderer_model.py` 定义 Spine 3.8 外部资源描述符与 SHA-256 校验边界（契约存在）。
- `create_configured_pet_renderer` 在 Spine 资源缺失时返回 `RUNTIME_UNAVAILABLE` → `PlaceholderPetRenderer`。
- 当前用户可见角色 = QPainter 程序化占位角色；Spine Runtime 尚未接入（无真实骨架资源）。

---

## 5. Dependency Map

以下基于 AST import 图 + 关键模块阅读得出（详见附录 A 方法说明）。

### 5.1 包级依赖

```text
domain            ←（无第三方依赖，被 application / infrastructure 反向依赖）
config            → domain（使用领域模型），不依赖 Qt/SDK
application       → domain, config（不得依赖 PySide6/OpenAI/SQLite ✓）
infrastructure    → domain, config（唯一允许接触 SDK / Windows API 的层）
presentation/qt   → application, infrastructure, config, domain
bootstrap         → application, infrastructure, config, presentation（组合根）
__main__.py       → bootstrap / application（CLI 演示入口）
packaging/pet_entry.py → presentation/qt/pet_application + 单实例
```

### 5.2 关键模块级依赖（经阅读确认）

```text
pet_window ──▶ pet_renderer ──▶ pet_renderer_model（渲染契约）
    │
    ├─▶ application/pet_state / pet_motion / pet_animation（行为状态机）
    ├─▶ presentation/qt/system_tray（右键菜单 / 托盘）
    └─▶ single_instance（启动前置判定）

runtime_bridge ──▶ runtime_thread ──▶ runtime_session_controller ──▶ agent_loop
application/autostart_service ──▶ infrastructure/autostart/windows_run_key
config/loader ──▶ config/models（不可变 RuntimeConfig）
infrastructure/llm/provider_factory ──▶ provider_registry ──▶ domain/ports
```

### 5.3 跨层注意点

- `application/pet_external_assets.py` 描述外部资源契约，但**实际文件系统访问在 `infrastructure/pet_external_asset_filesystem.py`**；契约与实现分居两层（合理，但阅读时容易混淆）。
- `application/` 内 Agent 与 Pet 模块目前**互不依赖**（同一目录的“并行邻居”），尚未形成跨子系统耦合 —— 这使未来按子系统拆分子包在依赖层面是低风险的（路径 import 除外）。
- `presentation/qt/` 同时承载：窗口 shell、桌宠窗口、渲染器、托盘、单实例、runtime 桥、autostart UI 控制器 —— 是本仓库依赖扇出最大的目录。
---

## 6. Architecture Findings

> 全部为“记录不修改”。每个发现都给出证据；证据不足的标注 Unknown，绝不直接判定 Unused。

### 6.1 `application/` 混装三个子系统（Responsibility Mixing）
- 证据：`application/` 同时包含 Agent（`agent_loop` / `context_manager` / `active_turn_coordinator` / `runtime_session_controller`）、Desktop Pet（`pet_state` / `pet_motion` / `pet_animation` / `pet_geometry` / `pet_mesh_model` / `pet_renderer_model` / `pet_settings` / `pet_external_assets`）、系统集成（`autostart_*` / `provider_*` / `startup_mode`）。
- 影响：目录名无法表达职责；新成员（如未来 Spine 动画控制器）难以判断归属。
- 缓解：三个子集目前互不 import，未来拆分是低耦合风险（但涉及路径 import 与 pytest 发现，仍属 Medium）。

### 6.2 `presentation/qt/` 承担过多职责（Layer / Responsibility Mixing）
- 证据：18 个已跟踪文件 + 1 个未提交 WIP（`control_center.py`）同时负责：窗口 shell、桌宠窗口、QPainter/OpenGL 渲染器、Spike、系统托盘、单实例、runtime 线程/桥、autostart UI 控制器、Provider 设置对话框、控制中心。
- 影响：`presentation/qt` 是依赖扇出最大的目录；“UI”与“平台集成”（托盘 / 单实例 / autostart 控制器）混在同一平面。
- 注意：这些模块之间存在真实 Qt 所有权约束（窗口↔渲染器↔托盘），未来拆分必须是**目录级**而非**架构级**。

### 6.3 `scripts/` 混装“运行脚本”与“测试支撑模块”
- 证据：`tests/unit/test_manual_credential_targets.py` / `test_manual_openai_verification.py` / `test_manual_deepseek_verification.py` import 了 `scripts/manual_*_verification.py`；`scripts/` 同时含 `run_*.py`、smoke、`test.ps1` / `typecheck.ps1`。
- 影响：测试依赖非测试目录 ⇒ 未来移动 `scripts/` 会破坏测试；`scripts/` 不是纯工具目录。
- 证据支撑：`pyproject.toml` 的 mypy `files` 显式包含 `scripts` 与 `packaging`，说明工具链已把二者当作“代码”而非“脚本”。

### 6.4 `packaging/` 五职责混装
- 证据：目录同时含 (1) 打包管线（`pet_entry.py` / `pysidedeploy.spec` / `build_standalone.ps1` / `prepare_packaging_environment.ps1`）、(2) 打包环境诊断（`packaging_environment_inventory.py` / `standalone_artifact_audit.py`）、(3) 依赖 walker 探针（`dependency_walker_*` 系列 + 2 个 `.c` 文件 + 多个 `*.ps1`）、(4) 运行时探针（`startup_secondary_*` / `windows_process_exit_observer.py` / `packaged_runtime_*`）、(5) 归档工具（`transactional_archive.py` / `archive_*`）。
- 影响：5 种生命周期完全不同的工具共存，`packaging/` 既被 `pysidedeploy.spec` 引用（Nuitka 模块清单）又被测试 import（`tests/unit/test_standalone_packaging.py` 等硬编码 `_PROJECT_ROOT / "packaging/<file>"`），任何移动都是高风险。

### 6.5 `build/` 成为一次性诊断临时区
- 证据：`build/` 下有约 200 个目录，命名前缀大量为 `autostart-*` / `smoke-*` / `temp-*` / `test-temp-*` / `uv-*`，属于一次性诊断产物而非构建产物；`build/` 本身在 `.gitignore` 中。
- 影响：污染仓库根目录视野；无法区分“真实构建输出”与“临时探针输出”。
- 缓解建议（未来）：建立 `build/artifacts/`（真实构建）与 gitignored 临时目录（如系统 TEMP 或 `build/_tmp/`）的约定，并让脚本统一入口。

### 6.6 `docs/` 扁平化 + 命名不一致
- 证据：14 篇工程文档平铺于 `docs/*.md`，命名混合主题（`configuration` / `pet_*` / `qt_*` / `system_tray` / `single_instance` / `windows_*`）；`ARKCLAW_UI_DESIGN_V1.md` 位于仓库根而非 `docs/`；`docs/superpowers/` 与 `docs/research/` 是另一套命名体系。
- 影响：文档查找依赖记忆文件名，而非目录导航。

### 6.7 命名不一致：ArkClaw / SJTUClaw / sjtuclaw
- 证据：Git 项目名 SJTUClaw、包名 `sjtuclaw`、二进制 `SJTUClaw.exe`、仓库目录名与 UI 文档使用 ArkClaw、Windows Run Key 值 `SJTUClaw`。
- 影响：跨脚本、文档、注册表键引用时容易拼错；属于“产品命名决策”，必须由用户拍板，不能由架构整理擅自统一。

### 6.8 测试硬编码仓库相对路径（High-Risk 依赖）
- 证据：`tests/unit/test_standalone_packaging.py` 等使用 `_PROJECT_ROOT / "packaging/<file>"`；`scripts/` 与 `packaging/` 脚本大量使用 `Path(__file__).resolve().parents[1]` 或 `sys.path.insert` 推断根目录。
- 影响：这些路径是未来迁移的“锁”：移动文件 = 必须同步改测试与脚本。

### 6.9 入口点被测试冻结
- 证据：`tests/unit/test_project_entry_points.py` 校验 3 个入口点（`sjtuclaw-agent-demo` / `sjtuclaw-gui` / `sjtuclaw-pet-placeholder`）与打包入口 `packaging/pet_entry.py`；`pysidedeploy.spec` 引用 `packaging/pet_entry.py`。
- 影响：入口点 = 稳定公共边界，未来不得改其行为或 import 目标；任何入口相关移动必须同步修改 pyproject + spec + 测试。

### 6.10 契约与实现分层导致阅读混淆（低严重度）
- 证据：`application/pet_external_assets.py` 是“资源契约描述”，`infrastructure/pet_external_asset_filesystem.py` 是“真实文件系统实现”；`application/pet_renderer_model.py` 是“渲染契约”，`presentation/qt/pet_renderer.py` 是“协议 + 适配”。
- 影响：按目录猜职责容易误判；“契约在 application / 实现在 infrastructure|presentation” 的约定需要文档化。

---

## 7. Stable Existing Boundaries

以下边界当前稳定，未来整理**不得破坏**：

1. **六层依赖规则**：`domain`/`application` 不依赖 PySide6 / OpenAI / SQLite；`infrastructure` 是唯一适配层。
2. **三入口点契约**：`sjtuclaw-agent-demo`、`sjtuclaw-gui`、`sjtuclaw-pet-placeholder`（pyproject + `test_project_entry_points.py` 冻结）。
3. **打包入口**：`packaging/pet_entry.py` 与 `pysidedeploy.spec` 的绑定关系。
4. **配置加载优先级**：CLI > env > app settings > defaults（`config/loader.py`）。
5. **Provider 体系**：`domain/ports.LLMProvider` ↔ `infrastructure/llm/provider_factory|registry` ↔ `config/provider_profiles` 的三段式契约。
6. **SecretStore 抽象**：`config/secrets.py` ↔ `infrastructure/security/windows_credential_store.py`。
7. **Pet 行为状态机契约**：`application/pet_state|pet_motion|pet_animation` 与 `presentation/qt/pet_window` 之间的调用关系（Relax/Move/Sit/Sleep/Special/Interact）。
8. **渲染契约**：`application/pet_renderer_model`（含 Spine 3.8 描述符）↔ `presentation/qt/pet_renderer` 协议 ↔ 外部资源 SHA-256 校验。
9. **单实例 / 托盘 / 自启动**：`single_instance.py` / `system_tray.py` / `infrastructure/autostart/windows_run_key.py` 的固定键值与行为。
10. **测试防网络约束**：`tests/conftest.py` 全局禁止非回环网络。

---

## 8. Current No-Touch Zones

> 这些系统当前工作正常；**不得为了“整理目录”而改动**。若某项调整存在改变其行为的风险，不执行并只在报告中标记。

| No-Touch 系统 | 涉及文件 | 保护理由 |
|---|---|---|
| Schwarz 角色渲染（当前为占位） | `presentation/qt/pet_renderer.py`、`application/pet_renderer_model.py` | 视觉呈现的直接来源 |
| 动画状态机（Relax/Move/Sit/Sleep/Special/Interact） | `application/pet_state.py` / `pet_motion.py` / `pet_animation.py` | 动画 timing / mix / 状态迁移 |
| 桌宠窗口几何与输入 | `presentation/qt/pet_window.py` | 尺寸、落点、click/drag/right-click、透明 hit-testing |
| OpenGL 网格后端 | `presentation/qt/pet_mesh_opengl_renderer.py` | 渲染后端行为 |
| BODY / OVERFLOW / Z-order / taskbar grounding | `pet_window.py` 相关逻辑 | 窗口层级与接地行为 |
| 托盘与右键菜单 | `presentation/qt/system_tray.py` | 菜单可用性 |
| 单实例判定 | `presentation/qt/single_instance.py` | 启动前置行为 |
| runtime 线程/桥 | `runtime_thread.py` / `runtime_bridge.py` | 异步关闭与命令边界 |
| Agent 核心 | `application/agent_loop.py` 等 | 回合事件流 / 超时 / 取消 |
| 自启动 | `infrastructure/autostart/*` + `application/autostart_*` | HKCU Run 键 `SJTUClaw` 行为 |
| 外部 Spine 资源契约 | `application/pet_external_assets.py` + `infrastructure/pet_external_asset_filesystem.py` | 资源解析与 SHA-256 校验 |
| 启动入口与打包 | `__main__.py`、`application.py`、`pet_application.py`、`packaging/pet_entry.py`、`pysidedeploy.spec` | 启动方式与打包行为 |
| 配置加载 | `config/*` | 优先级与不可变模型 |
---

## 9. Proposed Target Architecture

> 原则：**不创造当前不存在的抽象**。目标目录只做两类事：(1) 把已存在的稳定子系统放进各自目录；(2) 整理外围非运行时文件。`src/sjtuclaw/` 内部的分组全部使用“包内子包”表达，模块内容与 import 目标保持 1:1 不变。

```text
ArkClaw/                                  # （仓库目录名；产品命名统一由用户另行决策）
├── README.md / pyproject.toml / uv.lock / .env.example / .gitignore
│
├── src/sjtuclaw/                         # 唯一生产包（内容不变，仅目录分组）
│   ├── __main__.py                       # 入口：sjtuclaw-agent-demo（不动）
│   ├── bootstrap/                        # 组合根（不动）
│   ├── config/                           # 配置模型/加载/凭据边界（不动）
│   ├── domain/                           # 领域层（不动）
│   ├── application/
│   │   ├── agent/                        # ← 未来包内子包：agent_loop / context_manager /
│   │   │                                 #   active_turn_coordinator / runtime_session_controller
│   │   ├── pet/                          # ← 未来包内子包：pet_state / pet_motion / pet_animation /
│   │   │                                 #   pet_geometry / pet_mesh_model / pet_renderer_model /
│   │   │                                 #   pet_settings / pet_external_assets
│   │   └── system/                       # ← 未来包内子包：autostart_* / provider_* / startup_mode
│   │                                     #   （§6.1 三个子集互不依赖，拆分可行性高）
│   ├── infrastructure/                   # 适配层（不动，未来可再按 llm/security/persistence 分组）
│   └── presentation/
│       └── qt/
│           ├── pet/                      # ← 未来：pet_window / pet_renderer / pet_mesh_opengl_renderer
│           ├── ui/                       # ← 未来：main_window / control_center / provider_settings_dialog /
│           │                             #   pet_settings_controller / autostart_controller
│           ├── platform/                 # ← 未来：single_instance / system_tray / runtime_thread / runtime_bridge
│           └── (application.py / pet_application.py 保持入口地位，不归组)
│
├── tests/
│   ├── unit/ ── 按被测包再分组：unit/agent/ · unit/pet/ · unit/config/ · unit/infrastructure/…
│   ├── qt/
│   ├── integration/
│   ├── fakes/                            # 保持
│   └── support/                          # ← 未来：从 scripts/ 迁入 manual_*_verification.py 等测试支撑模块
│
├── scripts/                              # 未来只保留：run_*.py / smoke / test.ps1 / typecheck.ps1
├── packaging/                            # 未来只保留：打包管线本体 + spec（探针/诊断工具迁出）
├── tools/                                # ← 未来新目录：dependency_walker_*、startup_secondary_*、
│                                         #   windows_process_exit_observer、archive_*、packaging_environment_inventory
├── docs/
│   ├── product/                          # 产品/设计（UI 设计、research）
│   ├── design/                           # Spine 设计：superpowers/{plans,specs}
│   └── engineering/                      # 工程文档（本报告、configuration、providers、qt_*、windows_*）
│
├── build/
│   ├── artifacts/                        # ← 未来：真实构建输出
│   └── _tmp/                             # ← 未来：一次性探针统一放 gitignored 临时目录
│
└── dist/ / packaging/deployment/         # 生成物（保持 gitignored）
```

### 9.1 为什么这样设计

- **Cohesion**：`application/pet/*`、`presentation/qt/pet/*` 让“桌宠”职责可按目录导航；`application/agent/*` 让 Agent 核心可独立演进。
- **Separation of Concerns**：`presentation/qt/platform/*` 把平台集成（托盘/单实例/线程）从 UI 中分离，但**不改变对象所有权**（仍然是 Qt 层内部重组）。
- **Dependency Direction**：目录分组不改变 import 依赖方向；`domain ← application ← infrastructure ← presentation` 不变。
- **Minimal Change**：第一阶段**不移动 `src/` 任何文件**；`application` 子包拆分排在最高风险阶段（Phase 5），且按“一个子包一个 PR”粒度执行。
- **No Architecture Astronautics**：不引入 repository pattern / DI 框架 / event bus / 插件系统；只使用 Python 包与目录。

---

## 10. Current → Target Mapping

> 风险等级：**Low** = 纯文档或完全独立文件；**Medium** = 存在 import/path/test 依赖；**High** = 涉及 runtime loading / Qt / Windows native / Spine / asset paths / startup / packaging / dynamic import。
> 本阶段**不执行**任何移动；下表仅作未来规划。

| Current | Proposed | Reason | Risk |
|---|---|---|---|
| `docs/*.md`（14 篇扁平） | `docs/engineering/*.md` | 文档分类 | **Low** |
| `ARKCLAW_UI_DESIGN_V1.md`（根目录） | `docs/product/arkclaw-ui-design-v1.md` | 产品设计文档归位 | **Low**（仅链接/引用需同步） |
| `docs/research/`、`docs/superpowers/` | `docs/design/`（Spine 设计） | 分类统一 | **Low** |
| `scripts/manual_*_verification.py` | `tests/support/` | 测试支撑模块应归属测试 | **Medium**（被 `tests/unit/test_manual_*` import） |
| `scripts/`（其余） | `scripts/` 保留 | 运行/验证入口 | **Low** |
| `packaging/dependency_walker_*`（含 `.c`/`.ps1`） | `tools/dependency-walker/` | 探针工具独立 | **Medium**（`tests/unit/test_dependency_walker_*` 硬编码路径） |
| `packaging/startup_secondary_*`、`windows_process_exit_observer.py`、`packaged_runtime_*`、`archive_*`、`transactional_archive.py`、`packaging_environment_inventory.py` | `tools/` 或 `packaging/tools/` | 诊断/归档工具 | **Medium**（测试硬编码 `_PROJECT_ROOT / "packaging/…"`） |
| `packaging/pet_entry.py`、`pysidedeploy.spec`、`build_standalone.ps1`、`prepare_packaging_environment.ps1`、`standalone_build.py`、`production_import_smoke.py`、`standalone_artifact_audit.py` | `packaging/` 保留 | 打包管线本体 | **High**（spec/入口/测试三重绑定） |
| `application/agent_*` | `application/agent/` | 子系统内聚 | **High**（import 重写 + 测试发现 + mypy） |
| `application/pet_*` | `application/pet/` | 子系统内聚 | **High**（同上） |
| `application/autostart_*`、`provider_*`、`startup_mode.py` | `application/system/` | 系统集成内聚 | **High**（同上） |
| `presentation/qt/pet_window.py`、`pet_renderer.py`、`pet_mesh_opengl_renderer.py`、`pet_mesh_spike.py` | `presentation/qt/pet/` | UI 内聚 | **High**（Qt 所有权 + 测试） |
| `presentation/qt/main_window.py`、`control_center.py`、`provider_settings_dialog.py`、`pet_settings_controller.py`、`autostart_controller.py`、`owner_ui_readiness.py` | `presentation/qt/ui/` | UI 内聚 | **High**（Qt + 新 WIP） |
| `presentation/qt/single_instance.py`、`system_tray.py`、`runtime_thread.py`、`runtime_bridge.py` | `presentation/qt/platform/` | 平台集成内聚 | **High**（Qt 所有权） |
| `tests/unit/test_*.py` | `tests/unit/<subsystem>/` | 测试分组 | **Medium**（pytest 发现 + conftest） |
| `build/` 一次性探针目录 | `build/_tmp/` + 清理策略 | 临时区治理 | **Low**（仅脚本写入路径需同步） |
| `control_center.py`（WIP） | 跟随 `presentation/qt/ui/` 规划 | 归入 UI | **Medium**（未提交，先随功能 PR 稳定） |

---

## 11. Migration Risk Analysis

### 11.1 风险矩阵

| 迁移对象 | 破坏面 | 风险 | 主要依赖 |
|---|---|---|---|
| `docs/` 重组 | 文档内部相对链接、README 引用 | **Low** | README 中的 `docs/*.md` 链接 |
| `scripts/` 支撑模块迁入 `tests/support/` | `tests/unit/test_manual_*` import、mypy `files` | **Medium** | `sys.path`/相对 import |
| `packaging/` 工具迁出 | `tests/unit/test_standalone_packaging.py` 等硬编码路径、mypy `files` | **Medium–High** | `_PROJECT_ROOT / "packaging/<file>"` |
| `application/` 子包拆分 | 全仓 import、pytest 收集、mypy、ruff、入口 import | **High** | `from sjtuclaw.application.X import Y` |
| `presentation/qt/` 子目录分组 | Qt 对象所有权 import、`test_qt_*`、入口 | **High** | `from sjtuclaw.presentation.qt.X import Y` |
| `packaging/pet_entry.py` / spec | Nuitka 构建、独立发行 | **High** | `pysidedeploy.spec`、打包入口 |
| `build/` 临时区治理 | 诊断脚本的写出路径 | **Low** | 各探针脚本的 `Path(...)/build/...` |

### 11.2 高风险共性

- **import 路径**：`src/sjtuclaw/` 内移动文件 = 所有 import 重写（`rg "from sjtuclaw"` 可见数量巨大）。
- **测试硬编码路径**：`packaging/` 与 `scripts/` 被测试用绝对/相对路径引用，不是包路径。
- **启动与打包**：3 个 pyproject 入口 + `packaging/pet_entry.py` + Nuitka spec 互相绑定。
- **Qt 所有权**：`presentation/qt/` 内窗口↔渲染器↔托盘↔线程的生命周期是运行时事实，目录重组不得改变构造顺序。

### 11.3 缓解策略（未来执行时）

- 每个 High 风险阶段独立成 PR，且以“纯移动 + 仅改 import 头”为粒度。
- 移动前先跑完整基线（§13）；移动后逐项对照行为清单（§12）。
- 使用 `git mv` 保留历史；不合并多个子系统进同一提交。
- 每次移动后运行：pytest 全套、mypy、ruff、打包 smoke。
---

## 12. Behaviour Preservation Contract

> 任何未来目录整理必须满足：\[Behavior_{after} = Behavior_{before}\]。以下是必须保持的用户可观察行为清单（来自 README、文档与当前实现证据）。

### 12.1 Character（角色）
- Relax / Move / Sit / Sleep / Special / Interact 六类动作的名称与触发语义不变。
- 当前可见角色为 QPainter 占位角色（Spine Runtime 未接入）；占位角色的绘制外观与动画 timing 不变。
- 角色尺寸、落点（feet grounding）不变。

### 12.2 Geometry（几何）
- 桌宠窗口几何（尺寸 / 位置 / 落点）不变。
- taskbar overlap / grounding 行为不变。
- DPI 行为不变。

### 12.3 Input（输入）
- 点击（click）、拖拽（drag）、右键（right-click）行为不变。
- 透明像素保持点击穿透（transparent hit testing）不变。

### 12.4 Windowing（窗口）
- 透明无边框窗口、Z-order、BODY / OVERFLOW surface 语义不变。
- 系统托盘与右键菜单保持可用；单实例判定行为不变。

### 12.5 Startup（启动）
- 三个入口（`sjtuclaw-agent-demo` / `sjtuclaw-gui` / `sjtuclaw-pet-placeholder`）继续可用。
- `packaging/pet_entry.py` 打包入口与独立发行版继续可启动。
- 资源从现有路径加载成功（Spine 外部资源契约、settings JSON 路径）。

### 12.6 Runtime / Agent
- Agent 回合事件流、流式输出、超时 / 取消语义不变。
- Provider 生命周期（激活 / 关闭 / continuation 提交）不变。
- autostart（HKCU Run `SJTUClaw` 键）行为不变。

---

## 13. Regression Baseline

### 13.1 Automated Baseline（仓库真实命令，不虚构）

| 类别 | 命令 | 范围 |
|---|---|---|
| 单元测试 | `.\.venv\Scripts\python.exe -m pytest tests/unit` | 51 个 |
| Qt 测试（offscreen） | `.\.venv\Scripts\python.exe -m pytest tests/qt` | 15 个 + 1 子进程辅助 |
| 集成测试 | `.\.venv\Scripts\python.exe -m pytest tests/integration` | 2 个 |
| 全套 | `.\.venv\Scripts\python.exe -m pytest` | 上述全部 |
| 类型检查 | `.\.venv\Scripts\python.exe -m mypy`（配置含 src/tests/scripts/packaging） | 严格模式 |
| Lint | `.\.venv\Scripts\python.exe -m ruff check .` | E/F/I/UP/B/SIM/RUF |
| 脚本入口 | `scripts/test.ps1` / `scripts/typecheck.ps1` | 便捷入口 |
| 打包 smoke | `tests/unit/test_standalone_packaging.py` 等 | 打包相关模块 |

> 说明：`conftest.py` 全局禁止非回环网络，测试套件默认离线可跑；真实 OpenAI/DeepSeek 验证是显式手动路径（`scripts/manual_*_verification.py`），不属自动基线。

### 13.2 Manual Behaviour Baseline

每次 High 风险迁移后必须人工验证：

- **Character**：Relax / Move / Sit / Sleep / Special / Interact 正常。
- **Geometry**：feet grounding 不变、taskbar overlap 不变、角色尺寸不变、动画落点不变。
- **Input**：click / drag / right-click 不变、透明像素保持点击穿透。
- **Windowing**：Z-order 不变、BODY / OVERFLOW 不变、菜单可用。
- **Startup**：当前 launcher 继续工作、资源从既有路径加载。

---

## 14. Proposed Migration Phases

> 只生成计划，不执行。每阶段独立可回退（rollback = 该阶段的 `git revert` / 恢复该提交）。

### Phase 0 — Baseline Characterization（基线刻画）
- **Scope**：确认并固化 §13 自动基线；建立本报告为基线文档。
- **Non-Scope**：所有代码与文件。
- **Path Changes**：无。
- **Risk**：Low。
- **Tests**：全套 pytest + mypy + ruff 跑一遍并记录结果。
- **Manual**：启动三入口确认可用。
- **Rollback**：无文件变更，无需回退。

### Phase 1 — Documentation Organization（文档整理）
- **Scope**：`docs/*.md` → `docs/engineering/`；`ARKCLAW_UI_DESIGN_V1.md` → `docs/product/`；`docs/superpowers|research` → `docs/design/`（或保留）。
- **Non-Scope**：README 之外的代码；README 仅允许同步相对链接。
- **Path Changes**：README 与文档内相对链接。
- **Risk**：Low。
- **Tests**：无需代码测试；人工检查链接。
- **Manual**：打开文档确认链接可用。
- **Rollback**：单提交，可整体 revert。

### Phase 2 — Independent Non-Runtime Files（独立非运行时文件）
- **Scope**：`build/` 临时区治理约定（`build/artifacts/` + gitignored `build/_tmp/`）；删除/归档可证明的一次性探针目录（**需先逐个证明未被引用**）。
- **Non-Scope**：`src/`、`tests/`、`packaging/` 全部文件。
- **Path Changes**：被迁移诊断脚本的写出路径。
- **Risk**：Low–Medium。
- **Tests**：pytest 全套。
- **Manual**：无用户可见行为。
- **Rollback**：单提交。

### Phase 3 — Tests Organization（测试整理）
- **Scope**：`scripts/manual_*_verification.py` → `tests/support/`；`tests/unit/` 按子系统分组（仅移动 + 改 import）。
- **Non-Scope**：`tests/conftest.py` 行为；`tests/fakes/`。
- **Path Changes**：`test_manual_*` 的 import；mypy `files`（如需要）。
- **Risk**：Medium。
- **Tests**：pytest 全套 + mypy。
- **Manual**：无。
- **Rollback**：单提交。

### Phase 4 — Low-Risk Package Relocation（低风险包内迁移）
- **Scope**：`packaging/` 内非管线工具（dependency_walker / 探针 / 归档 / 环境清单）迁往 `tools/`，**保持 `pet_entry.py` + spec + 构建脚本原地不动**。
- **Non-Scope**：`packaging/pet_entry.py`、`pysidedeploy.spec`、`build_standalone.ps1`、`standalone_build.py`。
- **Path Changes**：`tests/unit/test_*packaging*.py` 中硬编码的 `_PROJECT_ROOT / "packaging/<file>"` 路径；mypy `files`。
- **Risk**：Medium–High（测试路径硬编码）。
- **Tests**：pytest 全套（重点 `test_standalone_packaging.py`、`test_dependency_walker_*`）+ mypy + ruff。
- **Manual**：无。
- **Rollback**：单提交。

### Phase 5 — Subsystem Migration（子系统迁移，最高风险）
- **Scope**：`application/` 拆为 `agent/` + `pet/` + `system/`；`presentation/qt/` 拆为 `pet/` + `ui/` + `platform/`。**每个子包一个独立提交**。
- **Non-Scope**：任何函数/类/API 改名；任何行为调整；`__main__.py` 与入口 import 目标。
- **Path Changes**：全仓 `from sjtuclaw.application.*` / `from sjtuclaw.presentation.qt.*` import 重写；`test_project_entry_points.py` 与 `pysidedeploy.spec` 中的模块路径。
- **Risk**：High。
- **Tests**：每子包移动后跑全套 pytest + mypy + ruff + 打包 smoke。
- **Manual**：三入口启动；桌宠动作清单（§13.2）逐项人工确认。
- **Rollback**：逐子包提交，各自可 revert。

### Phase 6 — Resources / Packaging（资源与打包）
- **Scope**：Spine 资源落地路径约定；`packaging/deployment/` 与 `dist/` 的产物管理约定。
- **Non-Scope**：Spine 资源内容；动画名称与 timing。
- **Path Changes**：`pet_external_assets` / `pet_external_asset_filesystem` 的路径解析（**必须由 Spine Runtime 功能 PR 一并验证**）。
- **Risk**：High（资源解析 + 打包）。
- **Tests**：全套 + 独立发行版启动 smoke。
- **Manual**：独立发行版全行为清单。
- **Rollback**：独立提交。

> **重要**：Phase 5 与 Phase 6 是“未来”阶段。在本报告被批准、且基线（Phase 0）固化之前，不启动任何移动。
---

## 15. Future Refactoring Candidates

> 本次调查发现的代码/结构问题，**全部未修改**。每个条目均需在独立 TDD 流程中单独解决。

### F1. `application/` 与 `presentation/qt/` 职责混装
- **Finding**：见 §6.1 / §6.2。
- **Evidence**：目录文件清单 + AST import 图。
- **Impact**：导航成本高；新功能归属判断困难。
- **Suggested future action**：按 §9 目标架构在 Phase 5 拆分子包。
- **Required separate TDD**：是（Phase 5 独立 PR + 全套回归）。

### F2. 测试与脚本的路径硬编码
- **Finding**：`_PROJECT_ROOT / "packaging/<file>"`、`Path(__file__).resolve().parents[1]`、`sys.path.insert` 散布于 tests / scripts / packaging。
- **Evidence**：`tests/unit/test_standalone_packaging.py` 等。
- **Impact**：任何文件移动都会连锁破坏；也是当前迁移风险的主要来源。
- **Suggested future action**：引入唯一的“仓库根解析”辅助（如 `tests/support/` 内的小工具）并逐步替换。
- **Required separate TDD**：是。

### F3. 契约层与实现层命名相似导致阅读混淆
- **Finding**：`pet_external_assets`（契约）vs `pet_external_asset_filesystem`（实现）；`pet_renderer_model`（契约）vs `pet_renderer`（协议+适配）。
- **Evidence**：§6.10。
- **Impact**：读者按目录猜职责易误判。
- **Suggested future action**：文档化“契约在 application / 实现在 infrastructure|presentation”约定；不改名。
- **Required separate TDD**：否（纯文档）。

### F4. 命名不一致 ArkClaw / SJTUClaw / sjtuclaw
- **Finding**：§6.7。
- **Evidence**：Git 项目名、包名、二进制名、README、`ARKCLAW_UI_DESIGN_V1.md`、Run Key。
- **Impact**：跨脚本/文档/注册表引用易出错。
- **Suggested future action**：由用户决策统一名称；若统一为 SJTUClaw，则仓库目录名与 UI 文档逐步对齐。
- **Required separate TDD**：是（涉及入口、打包、Run Key 时）。

### F5. `docs/` 扁平与分类缺失
- **Finding**：§6.6。
- **Evidence**：`docs/` 文件清单。
- **Impact**：文档可发现性差。
- **Suggested future action**：Phase 1 文档整理。
- **Required separate TDD**：否。

### F6. `build/` 一次性诊断目录膨胀
- **Finding**：§6.5。
- **Evidence**：约 200 个 `autostart-*` / `temp-*` / `test-temp-*` 目录。
- **Impact**：仓库根视野污染；磁盘占用。
- **Suggested future action**：Phase 2 临时区治理 + 定期清理（保留可证明有用的归档）。
- **Required separate TDD**：否（但删除前需证明未引用）。

### F7. Spine Runtime 尚未接入
- **Finding**：当前角色为 QPainter 占位；Spine 3.8 只有契约。
- **Evidence**：`pet_renderer_model.py`（SPINE38）+ `create_configured_pet_renderer` → `RUNTIME_UNAVAILABLE`。
- **Impact**：产品视觉目标未达成；不是结构问题。
- **Suggested future action**：跟随既有 `docs/superpowers/` 设计，独立功能 PR 实现，与本架构整理解耦。
- **Required separate TDD**：是。

### F8. `presentation/qt/` 中 spike 与生产代码同目录
- **Finding**：`pet_mesh_spike.py`、`pet_mesh_opengl_renderer.py`（spike 后端）与生产窗口共存。
- **Evidence**：文件清单 + `tests/qt/test_pet_mesh_opengl_spike.py`。
- **Impact**：难以区分“实验”与“生产”。
- **Suggested future action**：未来在 `presentation/qt/pet/` 下用 `experimental/` 或明确命名区分；不删除。
- **Required separate TDD**：否（仅归位）。

### F9. `packaging/` 内打包管线与诊断工具混装
- **Finding**：§6.4。
- **Evidence**：`packaging/` 文件清单。
- **Impact**：打包维护者难以区分“构建入口”与“探针”。
- **Suggested future action**：Phase 4 迁出工具；保留管线本体。
- **Required separate TDD**：是（测试硬编码路径）。

---

## 16. Unknowns

无法从当前仓库内容确定的事项：

1. **Spine 资源与 Runtime**：正式 Schwarz 角色资源是否已存在、何时落地、由谁生产 —— 仓库内只有契约与设计文档，没有资源文件。
2. **命名决策**：产品正式名称（ArkClaw vs SJTUClaw）由谁/何时统一 —— 属产品决策，不在代码中。
3. **`build/` 各临时目录的历史用途**：大部分可通过命名推断，但“哪些可安全删除”需要逐目录人工确认（本报告不判 Unused）。
4. **`packaging/` 探针工具的长期价值**：dependency_walker / startup_secondary / packaged_runtime 探针是否继续维护 —— 需与打包工作流所有者确认。
5. **WIP 的最终形态**：`control_center.py`、`main_window.py`、`pet_application.py` 的未提交修改尚未完成，其最终归属会随功能 PR 确定。
6. **CI 配置**：仓库当前**未见 CI 配置**（无 `.github/workflows` 等）；自动基线完全依赖本地命令。
7. **`worktrees` 状态**：`.worktrees/` 中的分支与主线关系未展开调查（gitignored，不影响当前审查结论）。

---

## 17. Post-Refactor Execution Record

> 本节记录 2026-08-14 当日审计之后实际执行的结构整理（P0–P5），供后续维护者核对。

### 17.1 已执行阶段

| 阶段 | 内容 | 提交 / 结果 |
|---|---|---|
| P0 基线保护 | 将工作树完整实现（`src/arkclaw/`、原生桥接改名、测试、文档）固化为可恢复提交 | `7a6fb3c`（工作树分支） |
| P1 基线验证 | 全量 pytest / ruff / mypy，记录环境相关失败 | pytest 3053 passed / 10 skipped / 10 failed；ruff 全过；mypy src 0 error |
| P2 结构整理 | `application/` 拆为 `agent/` `pet/` `system/`；`presentation/qt/` 拆为 `pet/` `ui/` `platform/`；入口 `application.py` / `pet_application.py` 留守 qt 顶层；仅同步 import/路径 | `9fc4f04`；P2 后全量回归与基线一致 |
| P3 文档同步 | `STRUCTURE.md`、交接文档 §4 目录树、打包预检模块路径同步到新结构；补 GPL 审计风险 | `f6e778a` |
| P4 主干切换 | main 旧版 WIP `git stash -u`（保留在 stash 可回退）；main 重置到 `f6e778a`；删除 `src/sjtuclaw` 残留缓存 | main @ `f6e778a`（ahead 64 / behind 2，未推送） |
| P5 终验 | 在 main 上重跑完整验证 | 见 17.3 |

### 17.2 重构后的最终目录结构

```text
ArkClaw/
├─ src/arkclaw/                    # 唯一正式生产包
│  ├─ domain/                      # 框架无关领域类型与端口
│  ├─ application/
│  │  ├─ agent/                    # Agent 会话、任务循环、运行会话控制
│  │  ├─ pet/                      # 桌宠动作、运动、状态、角色包、Track 0 编排
│  │  └─ system/                   # 开机启动、Provider profile、启动模式
│  ├─ bootstrap/                   # 生产组合根
│  ├─ infrastructure/
│  │  ├─ autostart/                # Windows 开机启动适配器
│  │  ├─ config/                   # 配置持久化仓库
│  │  ├─ llm/                      # Provider 适配器
│  │  └─ security/                 # Windows Credential Manager 等安全适配器
│  ├─ presentation/qt/
│  │  ├─ pet/                      # 桌宠窗口、renderer、overlay、Spine38 Qt 适配
│  │  ├─ ui/                       # 控制中心、菜单、对话框、设置控制器
│  │  ├─ platform/                 # 托盘、单实例、运行时桥接
│  │  ├─ application.py            # 普通 Qt/Agent 窗口入口（留守）
│  │  └─ pet_application.py        # 正式桌宠入口（留守）
│  └─ config/                      # 配置模型与加载规则
├─ native/spine38_bridge/          # Spine 3.8 C++ 桥接 DLL
├─ tests/                          # unit / qt / integration / fakes
├─ scripts/                        # 启动、构建、检查、smoke
├─ packaging/                      # Nuitka/Windows 打包与产物审计（暂缓整理）
├─ prototypes/                     # 可独立运行的诊断原型
├─ docs/                           # architecture / pet / rendering / providers / packaging / legal / engineering / superpowers
└─ build/                          # Git 忽略的本机构建产物
```

### 17.3 main 上终验结果（P5）

- `pytest`：**3057 passed / 10 skipped / 6 failed** —— 6 个失败与基线 10 个失败中的 6 个完全一致（无新增失败），均为无交互桌面环境导致（真实 GL / 系统托盘 / 菜单）。
- `ruff check src tests scripts packaging`：**全部通过**。
- `mypy src`：**0 error**（99 文件）；全量 mypy 49 errors 与基线一致，全在 7 个测试文件。
- `start_schwarz_pet.ps1 -ValidateOnly`：**通过**（manifest / bridge DLL / 素材路径全部解析）。
- `start_schwarz_pet.ps1 -Smoke`：**8/8 通过**（含 3 个 Relax 循环真实渲染、Sit 溢出像素、wrong-hash 探针、fallback 证明）。

### 17.4 未执行 / 暂缓项（记录原因）

- `packaging/` 工具分类（standalone_build 与 dependency_walker_cache 等裸 import + sys.path 互引）：移动会破坏现有可运行约定，风险大于收益，列为未来候选。
- `scripts/manual_*` 迁入 `tests/support/`：README 引用多，收益低。
- `tests/unit` 按子系统分组：纯 churn，收益低。
- `build/` 临时目录治理：gitignored 本地产物，不影响结构清晰度。
- `.claude` 加入 `.gitignore`：旧 main 有该行、新基线未保留；属本地工具配置，需要时再加。
- `origin/main` 推送：本地 main 已 ahead 64 / behind 2，**未推送**，需用户确认后 force-push。
- 失效 worktree `.worktrees/arkpets-spine-idle-vertical-slice`：与 main 同提交，可留作对照或按需清理。
- main 旧版 WIP（`ARKCLAW_UI_DESIGN_V1.md`、`control_center.py` 等）保留在 `git stash`，未并入新基线。

---

## Appendix A — 方法与证据

- **调查方法**：`rg --files` 全仓清单（排除 `.git/.venv/caches/build/dist/deployment`）→ 关键模块逐文件阅读（入口、组合根、Pet 管线、Agent 管线、基础设施、打包、测试）→ AST 解析构建模块级 import 图 → 跨文件引用扫描判定 `scripts/`、`packaging/` 的活/死状态 → 与 README / pyproject / docs 交叉核对。
- **基线**：git `main` @ `8b573dd`（v0.5），工作树含未提交 WIP（§2 备注）。
- **测试规模**：unit=51、qt=15、integration=2；`conftest.py` 禁止非回环网络。
- **生成物规模**：`packaging/deployment/` ≈ 720 MB；`dist/SJTUClaw.dist/` ≈ 133 MB（均 gitignored）。
- **约束遵守**：本阶段只新增本报告；未修改、移动、删除任何生产/测试/脚本/打包文件。

---

*报告结束。审计与结构整理（P0–P5）均已完成并通过回归验证，执行记录见 §17；`origin/main` 推送与后续清理项见 §17.4。*