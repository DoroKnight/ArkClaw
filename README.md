# ArkClaw

ArkClaw 是一个面向 Windows 的本地优先 2D AI 桌宠项目。第一阶段已经完成：当前保留的
主桌宠是接入 Spine 3.8 Runtime 和 Schwarz 角色素材的生产版本，程序化桌宠作为独立原型和
生产故障时的安全 fallback（安全降级）保留。

## 当前状态

生产桌宠已经具备：

- Schwarz Spine 3.8 骨骼、atlas 和纹理加载；
- `Relax`、`Move`、`Sit`、`Sleep`、`Special`、`Interact` 动作；
- 自主动作调度以及托盘、桌宠右键动作菜单；
- 左键单击互动、拖动、下落和落地；
- Special 扩展绘制 surface 和身体区域输入代理；
- 多显示器工作区、DPR 和窗口位置约束；
- DLL、manifest、素材或渲染失败时回退到程序化角色；
- 本地 Agent、Provider 设置、单实例、托盘和安全退出基础设施。

生产版本不把 Schwarz 素材提交到仓库。素材继续从本机外部目录加载；仓库只保存 Runtime
桥接、加载代码和本地 manifest 的生成逻辑。

## 目录结构

```text
ArkClaw/
├─ src/arkclaw/                  Python 正式源码
│  ├─ application/                桌宠状态、运动、动作和布局
│  ├─ bootstrap/                  正式桌宠与 Spine composition root
│  ├─ infrastructure/             Spine native adapter、Provider、持久化
│  └─ presentation/qt/            Qt 窗口、renderer、overlay、托盘
├─ native/spine38_bridge/         C++ Spine 3.8 桥接
├─ scripts/                       构建、正式启动和诊断脚本
├─ prototypes/placeholder_pet/    程序化桌宠原型入口与说明
├─ tests/                         unit、Qt、integration 测试
├─ docs/                          架构、桌宠、渲染和历史设计文档
├─ packaging/                     Windows 打包与制品检查
└─ build/                         本地构建产物和 manifest，不提交 Git
```

`PlaceholderPetRenderer` 仍位于正式 Python 包中，因为它是 Spine 加载或渲染失败时必需的
安全 fallback。`prototypes/placeholder_pet/` 单独保存强制启动原型的入口，不复制渲染源码，
避免维护两套逐渐分叉的实现。

更完整的交接结构见 [STRUCTURE.md](STRUCTURE.md)。

## 环境要求

- Windows 10/11；
- PowerShell 5.1 或 PowerShell 7；
- Python 3.12 或 3.13；
- `uv`；
- Visual Studio C++ Build Tools 和 CMake，用于构建 Spine 桥接；
- 已准备的 Schwarz Spine 3.8 素材。

当前已验证的素材目录是：

```text
D:\Spine\test\stage3_idle_rebuild_20260806_145235\runtime_input
```

目录内应包含：

```text
build_char_340_shwaz_striker#1.skel
build_char_340_shwaz_striker#1.atlas
build_char_340_shwaz_striker#1.png
```

## 第一次准备

以下命令假设仓库最终位于 `D:\ArkClaw`。当前改名工作树尚未物理移动时，请继续使用现有
工作树路径；`start_schwarz_pet.ps1` 会从脚本位置自动定位仓库，不依赖父目录名称。

在新的 PowerShell 中进入接入 Spine 的工作树：

```powershell
Set-Location 'D:\ArkClaw\.worktrees\arkpets-spine-idle-vertical-slice'
git status --short
uv sync --extra dev --extra gui
```

构建 Release 版 Spine 3.8 桥接并运行原生契约测试：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_spine38_bridge.ps1 -Configuration Release -RunTests
```

构建完成后应存在：

```text
build\spine38\Release\arkclaw_spine38_bridge.dll
```

只要没有修改 `native/spine38_bridge/`，以后启动时不需要重复构建 DLL。

## 在一个新的 PowerShell 中启动正式桌宠

推荐使用正式启动器。它会完成以下操作：

1. 定位当前工作树源码和虚拟环境；
2. 检查 DLL 与三个 Schwarz 素材文件；
3. 重新计算 SHA-256 并生成 `build/schwarz-production.local.json`；
4. 设置本次 PowerShell 所需的全部环境变量；
5. 强制从当前工作树 `src` 导入代码，避免共享 `.venv` 加载主仓库旧版本；
6. 使用 `pythonw.exe` 启动正式桌宠。

每次新开 PowerShell，只需要运行：

```powershell
Set-Location 'D:\ArkClaw\.worktrees\arkpets-spine-idle-vertical-slice'
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_schwarz_pet.ps1
```

如果素材位于其他目录：

```powershell
Set-Location 'D:\ArkClaw\.worktrees\arkpets-spine-idle-vertical-slice'
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_schwarz_pet.ps1 -AssetRoot 'D:\你的素材目录'
```

启动前请先从旧桌宠的托盘菜单选择 `Quit`。应用启用了单实例保护；已有桌宠未退出时，
第二次启动不会创建另一个窗口。

### 控制台排错启动

需要观察 Python 或 Qt 错误时使用：

```powershell
Set-Location 'D:\ArkClaw\.worktrees\arkpets-spine-idle-vertical-slice'
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_schwarz_pet.ps1 -Console
```

该命令使用 `python.exe`，桌宠退出前 PowerShell 会保持占用，这是正常行为。

### 只验证路径，不打开窗口

```powershell
Set-Location 'D:\ArkClaw\.worktrees\arkpets-spine-idle-vertical-slice'
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_schwarz_pet.ps1 -ValidateOnly
```

第一行必须指向：

```text
D:\ArkClaw\.worktrees\arkpets-spine-idle-vertical-slice\src\arkclaw\presentation\qt\pet_application.py
```

同时必须显示：

```text
Python runtime: D:\ArkClaw\.worktrees\arkpets-spine-idle-vertical-slice\.venv\Scripts\python.exe
```

如果指向 `D:\ArkClaw\src\...`，说明启动的是主仓库旧代码，而不是当前工作树版本。

## 完整手工启动命令

以下命令与正式启动器等价，适合检查环境变量和启动机制。要求本地 manifest 已由正式启动器
生成；若尚未生成，请先执行一次 `-ValidateOnly`。

```powershell
Set-Location 'D:\ArkClaw\.worktrees\arkpets-spine-idle-vertical-slice'

$assetRoot = 'D:\Spine\test\stage3_idle_rebuild_20260806_145235\runtime_input'
$env:PYTHONPATH = (Resolve-Path 'src').Path
$env:ARKCLAW_SPINE38_BRIDGE_DLL = (Resolve-Path 'build\spine38\Release\arkclaw_spine38_bridge.dll').Path
$env:ARKCLAW_PET_ROLE_MANIFEST = (Resolve-Path 'build\schwarz-production.local.json').Path
$env:ARKCLAW_SPINE38_ASSET_ROOT = (Resolve-Path -LiteralPath $assetRoot).Path

.\.venv\Scripts\pythonw.exe -c "from arkclaw.presentation.qt.pet_application import run; run()"
```

`PYTHONPATH` 不能省略。当前工作树的 `.venv` 与主仓库共享，editable install 记录的路径可能仍是
`D:\ArkClaw\src`；显式设置它才能确保载入正确版本。

## 工作树环境检查

当前工作树和 Git 元数据均已迁移到 `D:\ArkClaw`。工作树中的 `.venv`、`.venv-packaging`
分别连接到主仓库的共享环境。使用以下命令检查环境是否健康：

```powershell
Set-Location 'D:\ArkClaw\.worktrees\arkpets-spine-idle-vertical-slice'
git status --short
.\.venv\Scripts\python.exe -c "import arkclaw; print(arkclaw.__file__)"
```

如果工作树的共享 `.venv` junction 日后再次失效，正式启动器仍会自动尝试
`D:\ArkClaw\.venv`，并在两个位置都不可用时列出全部检查过的路径。

### 用户数据和系统集成影响

本次是完整身份切换，不会继续读取旧命名空间：

- 环境变量改为 `ARKCLAW_*`；
- Windows Credential Manager Target 改为 `ArkClaw/...`；
- HKCU Run 值名改为 `ArkClaw`；
- 单实例命名空间改为 `ArkClaw.Pet.SingleInstance.V1`；
- Provider 元数据目录改为 `%LOCALAPPDATA%\ArkClaw`；
- Qt 应用名和组织名均改为 `ArkClaw`。

为避免未经确认复制凭据，新版本不会自动迁移旧 Credential Target。需要在 ArkClaw 设置界面重新
保存 API Key；旧凭据可以在确认新版本工作正常后再手工删除。若旧开机启动项仍存在，也应先在
旧版本中关闭，或在 Windows 启动应用设置中禁用。

安装入口更新后也可以运行：

```powershell
.\.venv\Scripts\arkclaw-pet.exe
```

但在共享虚拟环境的开发工作树中，推荐继续使用 `start_schwarz_pet.ps1`。旧入口
`arkclaw-pet-placeholder.exe` 只作为兼容别名保留，不再作为 README 的正式启动方式。

## 启动程序化桌宠原型

原型入口会主动清除 Spine 环境变量，保证显示程序化角色：

```powershell
Set-Location 'D:\ArkClaw\.worktrees\arkpets-spine-idle-vertical-slice'
powershell -NoProfile -ExecutionPolicy Bypass -File .\prototypes\placeholder_pet\start_placeholder_pet.ps1
```

控制台模式：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\prototypes\placeholder_pet\start_placeholder_pet.ps1 -Console
```

原型与正式桌宠共享单实例保护，二者不能同时运行。详细说明见
[程序化桌宠原型](prototypes/placeholder_pet/README.md)。

## Schwarz 桌宠人工验收

以下是本项目唯一推荐的人工验收入口。开始前先从已有桌宠的托盘菜单选择 `Quit`，避免
单实例保护拦截新进程。

### 1. 自动预检

先让启动器生成并验证本地配置：

```powershell
Set-Location 'D:\ArkClaw\.worktrees\arkpets-spine-idle-vertical-slice'
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_schwarz_pet.ps1 -ValidateOnly
```

运行真实 Schwarz catalog 和 smoke。`-Smoke` 会在启动器自己的 PowerShell 进程中完成环境配置和测试，
不依赖子进程退出后保留环境变量：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_schwarz_pet.ps1 -Smoke
```

通过标准：

- `-ValidateOnly` 输出当前工作树源码路径；Python 路径优先使用工作树
  `.venv`，不存在时应明确回退到 `D:\ArkClaw\.venv`；
- `-Smoke` 最终输出的通过数量以当前收集到的真实 catalog/smoke 用例为准，且不得有失败；
- 不得出现 `composition_failed`、`ABI_MISMATCH` 或素材 hash 错误。

### 2. 打开用于人工验收的桌宠

```powershell
Set-Location 'D:\ArkClaw\.worktrees\arkpets-spine-idle-vertical-slice'
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_schwarz_pet.ps1 -Console
```

PowerShell 在桌宠退出前保持占用是正常行为。右键桌宠或系统托盘选择动作。

### 3. 固定动作序列

先在托盘或桌宠右键菜单开启 `Always on Top`。依次执行并完整观察：

```text
Relax → Sit（三个完整循环）→ Relax
Move Left → Sit（三个完整循环）→ Relax
Move Right → Sit（三个完整循环）→ Relax
Sit → Sit → Sit → Relax
```

通过标准：

- Sit 尾巴末端全程自然完整，没有贴着透明窗口边缘的齐边断口；
- Sit 脚部真实像素越过任务栏上沿，并显示在任务栏内容之上；
- Sit 屁股仍保持原任务栏上沿位置，BODY 窗口不向上移动；
- RIGHT 和 LEFT 两个朝向都满足尾巴完整、脚部覆盖任务栏；
- Sit 循环和 Relax/Move 切入、切出时没有闪烁、残影、双影或纵向跳动；
- Move、Relax、Sleep、Special、Interact 的原有表现不变；
- 拖动、松手、落地后仍能继续执行上述动作序列。

至少保存一段不少于 15 秒、同时包含任务栏、全身、动作切换和两个朝向的视频；另保存
RIGHT/LEFT 尾巴最外扩帧各一张，以及一张脚部覆盖任务栏的中段截图。自动测试和截图都不能
单独代替上述动态目视验收。

### 4. 显示器矩阵

至少在 Windows 显示缩放 `100%`、`125%`、`150%`、`200%` 下重复
`Relax → Sit → Move → Relax`。有多显示器时还要在主屏、副屏、负坐标屏幕以及跨屏后复验。

最终通过条件是：所有 grounded 动作的窗口底边始终贴合当前屏幕可用工作区底边，肉眼看不到
动作切换引起的纵向位移。自动 Smoke 不能替代这一项视觉确认，建议保存包含任务栏的录屏。

### 5. 开发回归测试

运行桌宠相关回归测试：

```powershell
.\.venv\Scripts\python.exe -m pytest tests\unit\test_pet_render_layout.py tests\unit\test_pet_production_motion.py tests\qt\test_pet_effect_overlay.py tests\qt\test_pet_window.py -q
```

完整质量检查：

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check src tests scripts packaging
.\.venv\Scripts\python.exe -m mypy src tests scripts packaging
git diff --check
```

## 桌宠操作参考

- 左键单击桌宠：播放 `Interact`；
- 左键按住并移动：拖动桌宠，松开后进入下落和落地；
- 右键桌宠或右键系统托盘：选择 `Move`、`Sit`、`Sleep`、`Special`、`Interact`；
- `Resume Autonomous`：恢复自主行为；
- `Always on Top`：切换置顶；
- `Quit`：走安全退出流程。

## Agent 与普通 Qt 窗口

运行离线 Agent 演示：

```powershell
.\.venv\Scripts\arkclaw-agent-demo.exe
```

运行普通 Provider 设置窗口：

```powershell
.\.venv\Scripts\arkclaw-gui.exe
```

桌宠启动不会自动激活云端 Provider，也不会自动发送网络请求。

## 架构约束

- `domain/` 和 `application/` 不得依赖 PySide6、OpenAI、SQLite 或具体 Spine adapter；
- Qt 代码位于 `presentation/qt/`；
- C++ Runtime 通过 `infrastructure/spine38_native.py` 和 native bridge 隔离；
- 正式角色加载失败必须 fail closed 到程序化 fallback，不能导致 Qt timer 异常退出；
- Spine 素材、生成的 manifest、DLL 和构建缓存不得提交 Git；
- 保留既有文件名、类名和公共接口，除非设计审查明确批准迁移。

相关文档：

- [Schwarz 生产动画](docs/rendering/schwarz_production_animation.md)
- [Spine 3.8 本地垂直切片](docs/rendering/spine38_local_vertical_slice.md)
- [桌宠设置](docs/pet/pet_settings.md)
- [系统托盘](docs/pet/system_tray.md)
- [单实例运行](docs/architecture/single_instance.md)
- [Provider 架构](docs/architecture/provider_architecture.md)
- [Windows 打包预检](docs/packaging/windows_packaging_preflight.md)
