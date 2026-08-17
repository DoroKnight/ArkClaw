# ArkClaw

> 本地优先的 Windows 桌面 AI 产品 · V1 Release Candidate 1（Alpha）

ArkClaw 是一个 **Character-first Desktop Agent（角色优先的桌面 Agent）**。

桌面上，一个可替换的动画桌面角色（Active Character）是主要交互入口，负责角色存在、
快速指令与轻量对话；当需要更深入的对话与 Agent 工作时，ArkClaw 按需展开为一个完整
应用（Full App / Dashboard）。实际工作由后端 Agent 承担，前端负责对话、活动与结果的
呈现。

它同时拥有三层结构，属于同一个产品、共享同一套权威 presentation state：

```text
ArkClaw
│
├── Desktop Companion（桌面伴侣）
│   ├── Active Character      角色存在 / 快速交互 / 状态表达
│   ├── Action Palette        快捷指令
│   └── Conversation Capsule  轻量对话
│
├── Full App / Dashboard（完整应用）
│   ├── Home
│   ├── Chat / Work
│   └── Character Animation
│
└── Backend Agent（后端 Agent，负责实际任务执行）
```

## 产品定位

ArkClaw 不是普通桌宠、不是单纯 Spine 动画播放器，也不是传统聊天软件、IDE 或重型控制
面板：桌面角色是产品的 embodiment、交互入口与状态表达，而不是产品能力的全部。

- **Character First**：桌面默认只保留 Active Character，角色是用户接触 ArkClaw 的第一入口；
- **Conversation First**：自然语言是最高层的主要交互方式，用户不必为普通 Agent 任务学习复杂 UI；
- **UI on Demand**：不需要 UI 时桌面只有角色；简单操作使用 Action Palette / Conversation Capsule；完整交互进入 Full Dashboard；
- **Progressive Disclosure**：界面复杂度随任务复杂度逐步增加，而不是一开始就给出 IDE 式工作区；
- **Calm Desktop**：默认安静，不长期占据屏幕，无常驻工具条、仪表或遥测；
- **Agent State Visible**：UI 与角色动画共同表达 Idle / Listening / Thinking / Working / Waiting / Needs Attention / Completed / Error，但反馈克制，不做高频 HUD 动画。

## 产品体验

### Desktop Companion（桌面伴侣）

轻量日常入口，负责角色存在、快速交互、快速指令与快速提问，不是完整应用本体。

- **Active Character**：默认桌面状态只有角色。参考素材为 Schwarz，通过生产 Spine 3.8
  Runtime 渲染；素材缺失或加载失败时安全回退到程序化桌宠（fail-closed）。
- **Action Palette**：右键角色打开，ROOT → `Ask ArkClaw` / `Character` / `System`，
  同壳导航（Back/Escape 返回 ROOT）。采用 Windows native 策略
  `Qt.Tool | FramelessWindowHint`（`Qt.Popup` 已淘汰），锚定在角色旁。
- **Conversation Capsule**：轻量对话容器，绑定唯一权威 `ConversationContext`
  （草稿、revision、IME），适合快速提问与简短回答；复杂任务进入 Dashboard 的 Chat / Work。

### Full App / Dashboard（完整应用）

独立应用窗口，用户可主动打开，用于完整对话、Agent 工作、附件、结果与角色动画管理。
它不是默认常驻桌面的窗口：打开 Dashboard 不意味着角色消失，关闭后桌面回到轻量
角色优先状态。

V1 一级结构刻意保持精简：

- **Home**：产品介绍、功能导航、最近工作入口（无数据时显示显式空态）、Active
  Character 摘要与轻量 Agent 状态。它不是遥测 / 指标仪表盘。
- **Chat / Work**：对话与 Agent 工作合一的连续流程 —— 对话 → 任务请求 → Agent 工作 →
  进度 → 结果 → 追问。实际工作由后端 Agent 负责，前端呈现输入、对话、附件、Agent
  状态、活动、结果与后续交互；它不是前端自行完成的自动化，也不是 IDE。
- **Character Animation**：当前角色是谁、支持哪些动画。目标能力包括 Active Character、
  角色选择、Spine 预览、动画清单、动画预览 / 播放、Trigger on Desktop。动画清单由
  Active Character 的 manifest / 能力驱动，不同角色可暴露不同动画能力。

### 体验流程

```text
Active Character
   │
   ├── Left Click → Interact（互动）
   ├── Drag       → 移动角色
   └── Right Click → Action Palette
          ├── Ask ArkClaw → Conversation Capsule
          ├── Character
          └── System

轻量对话         → Conversation Capsule
更深入对话 / 工作 → Full Dashboard > Chat / Work
```

## 角色模型

- **Active Character**：产品级术语。角色提供个性与动画，ArkClaw 提供稳定的产品界面；
  角色是可替换的，UI（Action Palette、对话、Dashboard、导航）与具体角色解耦。
- **Schwarz / 黑**：当前参考角色（Current reference character），用于视觉与工程验证。
  Schwarz 并不永久绑定 ArkClaw，未来可切换到其他兼容角色。
- **V1 角色资产范围**：有意聚焦于兼容 Arknights 风格 chibi / 小型 Spine 角色资产；
  不是 Live2D、3D、GIF、静态 PNG 或任意角色引擎；V1 不包含角色市场 / 动画编辑器。

## 视觉方向

Google / Material 启发的现代生产力 UI + 角色优先的桌面交互模型：

- Chrome → App Shell 的轻量外壳；
- Chrome + Gmail → 导航与功能组织；
- Gemini → 对话 / Composer / Agent 工作呈现；
- Google Material → 共享视觉系统。

视觉语言：中性表面、充足留白、柔和圆角、清晰排版、克制阴影与动效、低视觉噪声；
避免 game HUD、cyberpunk、neon、重度战术风。

> 角色负责个性与动画表达，界面负责稳定、统一、与角色无关的产品结构。

## 当前状态（Implemented）

以下为仓库中已经实现并验证的内容：

- Desktop Companion：Active Character（Schwarz 参考素材）经 Spine 3.8 生产渲染；
  左键 Interact、拖动 / 下落 / 落地、右键 → Action Palette
  （`Qt.Tool | FramelessWindowHint`），ROOT / Character / System 同壳导航；
- Conversation Capsule 绑定唯一权威 `ConversationContext`，草稿 / revision / IME 安全；
- 系统托盘（含 Open Dashboard 入口，可打开 Full Dashboard）、单实例、Windows 开机启动、安全退出；
- Dashboard：桌宠进程内懒加载的唯一第二顶层窗口（纯 presentation transition，零会话、
  零后端任务），重开复用同一窗口；App Shell 下 Home / Chat / Work / Character Animation
  三个页面，与桌面共享同一 presentation model；
- Chat / Work 渲染 Conversation、Task State、Activity、Result / Artifact 与冻结规格
  Composer；Agent Error 保留上下文与草稿，失败结果渲染 `Failed` + 恢复动作；
- Character Animation：Active Character 头、能力驱动角色选择器、Spine 预览位
  （当前为标注占位）、能力驱动动画清单（真实 Unavailable / Trigger-unavailable 状态）；
- 视觉：Visual Freeze v1 语义 token；Light / Dark 同源；键盘 / 焦点 / Reduced Motion；
  Action Palette 与托盘菜单采用 token 主题并锚定角色旁。

当前验证基线：自动化回归与 Windows native 交互门禁通过，详见
[V1_VALIDATION_REPORT.md](docs/release/V1_VALIDATION_REPORT.md)。

## V1 方向（Planned）

已明确设计、但仍在实现中的第一版体验：

- 后端 Agent 真实任务执行：目前 Dashboard 提交只捕获 inert snapshot，不调用 Provider；
- Dashboard 内真实 Spine 预览：目前为占位帧；
- 真实附件 / 上传传输：目前仅为 presentation 层状态；
- Desktop ↔ Dashboard 连续性、Agent 状态呈现、附件 / 结果呈现的完整闭环；
- 更完整的视觉一致性（Light / Dark）与角色切换。

V1 一级结构仅 Home / Chat / Work / Character Animation；不包含 Materials / Projects /
Tasks / Files / Tools / Models / Plugins / Agents 一级页面。

## 长期方向（Future）

ArkClaw 的长期方向是从动画桌面伴侣 + 对话 + 快速指令，逐步发展为**能够承载 Agent
交互、表达 Agent 状态、并帮助用户完成实际桌面工作的 embodied desktop interface**。
未来可以探索：

- 更丰富的 Agent 工作流（conversation → task understanding → tool use → desktop action → result presentation）；
- 桌面应用 / 工具集成、文件与项目上下文、浏览器辅助工作流；
- 更好的结果 / artifact 呈现；
- 更大、更兼容的 Arknights 风格 chibi Spine 角色库与更丰富的角色状态动画映射；
- 长期素材管理（Materials Library，仅在未来需求确认后考虑，不是 V1 一级页面）。

以上均为方向性探索，不构成当前承诺；character marketplace 不在当前计划内。

## 工程原则

- 角色行为不因 UI 演进而回归；
- presentation state 有明确归属；
- UI 不得虚构后端能力；
- Windows native 行为以测试验证而非假设；
- 角色输入回归有专门保护。

## 环境要求

- Windows 10/11；
- PowerShell 5.1 或 PowerShell 7；
- Python 3.12 或 3.13；
- `uv`；
- Visual Studio C++ Build Tools 和 CMake，用于构建 Spine 桥接；
- 已准备的 Schwarz Spine 3.8 素材（仓库外）。

当前已验证的素材目录：

```text
D:\Spine\test\stage3_idle_rebuild_20260806_145235\runtime_input
```

目录内应包含：

```text
build_char_340_shwaz_striker#1.skel
build_char_340_shwaz_striker#1.atlas
build_char_340_shwaz_striker#1.png
```

## 快速开始

### 1. 安装依赖

```powershell
Set-Location 'D:\ArkClaw'
uv sync --extra dev --extra gui
```

### 2. 构建 Spine 3.8 桥接（首次或修改 `native/` 后）

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_spine38_bridge.ps1 -Configuration Release -RunTests
```

构建完成后应存在 `build\spine38\Release\arkclaw_spine38_bridge.dll`。没有修改
`native/spine38_bridge/` 时，之后启动无需重复构建。

### 3. 启动正式桌宠

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_schwarz_pet.ps1
```

启动器会自动完成：定位仓库与虚拟环境 → 校验 DLL 与三个素材文件 → 重新计算 SHA-256
并生成 `build/schwarz-production.local.json` → 设置全部环境变量 → 用 `pythonw.exe`
启动正式桌宠（单实例保护）。

如果素材位于其他目录：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_schwarz_pet.ps1 -AssetRoot 'D:\你的素材目录'
```

其他模式：

- `-Console`：控制台运行，便于观察 Python/Qt 错误；
- `-ValidateOnly`：只校验环境并输出路径；
- `-Smoke`：运行真实 Schwarz catalog 与 smoke 测试。

启动前请先从旧桌宠的托盘菜单选择 `Quit`。应用启用单实例保护；已有桌宠未退出时，
第二次启动不会创建另一个窗口。

### 4. 其他入口

```powershell
.\.venv\Scripts\arkclaw-gui.exe          # 控制中心 / Provider 设置窗口
.\.venv\Scripts\arkclaw-agent-demo.exe   # 离线 Agent 演示
.\.venv\Scripts\arkclaw-pet.exe          # 桌宠（与启动器等价）
```

- **Dashboard**：桌宠进程内懒加载的唯一第二顶层窗口
  （`PetApplicationCoordinator.open_dashboard()` presentation seam），可从托盘菜单
  `Open Dashboard` 打开。打开是纯 presentation transition，不触发后端任务，不创建
  重复实例。
- 桌宠启动不会自动激活云端 Provider，也不会自动发送网络请求。

## 桌宠操作参考

- 左键单击桌宠：播放 `Interact`；
- 左键按住并移动：拖动桌宠，松开后进入下落和落地；
- 右键桌宠：打开 Action Palette（ROOT → Character / System / Ask ArkClaw，
  Back/Escape 返回 ROOT；再次右键/点击外部关闭）；
- 右键系统托盘：保留既有菜单语义（`Resume Autonomous`、`Always on Top`、
  `Open Dashboard`、`Quit` 等）。

## 目录结构

```text
ArkClaw/
├─ src/arkclaw/                  Python 正式源码
│  ├─ application/                桌宠、Agent、系统应用层
│  ├─ bootstrap/                  composition root
│  ├─ infrastructure/             Spine bridge、Provider、持久化
│  └─ presentation/qt/            窗口、Action Palette、Dashboard、theme
├─ native/spine38_bridge/         C++ Spine 3.8 桥接
├─ scripts/                       构建、启动、smoke 脚本；debug/ 存放调试脚本
├─ tests/                         unit / qt / integration / fakes 测试
├─ docs/                          设计、工程、release、legal 文档
├─ packaging/                     Windows 打包预检
└─ build/                         本地构建产物与 manifest，不提交 Git
```

更完整的交接结构见 [STRUCTURE.md](STRUCTURE.md)。

## 测试与质量门

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check src tests scripts packaging
.\.venv\Scripts\python.exe -m mypy src tests scripts packaging
git diff --check
```

Native 测试需要生产环境变量（`ARKCLAW_SPINE38_BRIDGE_DLL`、
`ARKCLAW_PET_ROLE_MANIFEST`、`ARKCLAW_SPINE38_ASSET_ROOT`）与 `QT_QPA_PLATFORM=windows`；
缺失时相关节点会按环境门控 skip。当前验证基线见
[V1_VALIDATION_REPORT.md](docs/release/V1_VALIDATION_REPORT.md)。

## 架构约束

- `domain/` 和 `application/` 不得依赖 PySide6、OpenAI、SQLite 或具体 Spine adapter；
- Qt 代码位于 `presentation/qt/`；Dashboard/桌面共享同一 presentation model；
- C++ Runtime 通过 `infrastructure/spine38_native.py` 和 native bridge 隔离；
- 正式角色加载失败必须 fail-closed 到程序化 fallback，不能导致 Qt timer 异常退出；
- Spine 素材、生成的 manifest、DLL 和构建缓存不得提交 Git；
- `PetWindow` 不拥有 Palette host，只发出 presentation 请求；command 执行回到
  既有应用回调；
- 保留既有文件名、类名和公共接口，除非设计审查明确批准迁移。

## License / 资产声明

当前 License 为 **Proprietary（专有）**，声明于 `pyproject.toml`。仓库根目录暂不包含
`LICENSE` 文件：GPL-3.0-only 迁移审计正在进行且整体状态为 **BLOCKED**
（见 [docs/legal/gpl_migration_audit.md](docs/legal/gpl_migration_audit.md)）。
在审计各项证据关闭之前，不会改动根 LICENSE、README License 声明或包元数据。

角色素材与相关 IP 仍归其各自所有者和许可方；角色素材不提交仓库，仅从本机外部目录
加载。本 README 不构成对 Arknights 或任何角色 IP 的官方集成或分发授权声明。

## 文档导航

- [STRUCTURE.md](STRUCTURE.md) — 目录结构
- [Summary.md](Summary.md) — 项目阶段总结
- [docs/release/](docs/release/) — V1 发布说明、已知限制、验证报告、架构状态
- [docs/design/](docs/design/) — 冻结的 Visual Design System v1
- [docs/legal/gpl_migration_audit.md](docs/legal/gpl_migration_audit.md) — License 迁移审计
- [docs/packaging/windows_packaging_preflight.md](docs/packaging/windows_packaging_preflight.md) — Windows 打包预检