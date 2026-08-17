from pathlib import Path
wt = Path(r"D:\ArkClaw\.worktrees\arkpets-spine-idle-vertical-slice")

def replace_block(rel, start_marker, end_marker, new_block):
    p = wt / rel
    lines = p.read_text(encoding="utf-8").splitlines(keepends=True)
    si = ei = None
    for i, l in enumerate(lines):
        if si is None and start_marker in l:
            si = i
        elif si is not None and end_marker in l:
            ei = i
            break
    assert si is not None and ei is not None, f"{rel}: markers not found"
    nl = "\r\n" if lines[si].endswith("\r\n") else "\n"
    new_lines = [b + nl for b in new_block.rstrip().split("\n")]
    lines[si:ei] = new_lines
    p.write_text("".join(lines), encoding="utf-8")
    print(f"block edited {rel}")

def replace_exact(rel, old, new, count=1):
    p = wt / rel
    s = p.read_text(encoding="utf-8")
    n = s.count(old)
    assert n == count, f"{rel}: expected {count} of {old!r}, found {n}"
    p.write_text(s.replace(old, new), encoding="utf-8")
    print(f"exact edited {rel}")

replace_block(
    r"STRUCTURE.md",
    "src/arkclaw/",
    "```",
    """src/arkclaw/
├─ domain/                  # 框架无关的领域类型与端口
├─ application/
│  ├─ agent/                # Agent 会话、任务循环与运行会话控制
│  ├─ pet/                  # 桌宠动作、运动、状态、角色包与 Track 0 编排
│  └─ system/               # 开机启动、Provider profile 与启动模式
├─ bootstrap/               # 正式 composition root
├─ infrastructure/
│  ├─ autostart/            # Windows 开机启动适配器
│  ├─ config/               # 配置持久化仓库
│  ├─ llm/                  # Provider 适配器
│  └─ security/             # Windows Credential Manager 等安全适配器
├─ presentation/qt/
│  ├─ pet/                  # 桌宠窗口、renderer、overlay 与 Spine38 Qt 适配
│  ├─ ui/                   # 控制中心、菜单、对话框与设置控制器
│  └─ platform/             # 托盘、单实例与运行时桥接
└─ config/""",
)

replace_exact(
    r"STRUCTURE.md",
    "当前工作树包含第一阶段实现的未提交改动，整理时不得丢弃或覆盖这些改动。",
    "当前工作树基线（`src/arkclaw/` 完整实现）已提交。结构整理只允许移动文件并同步依赖路径，不得改变任何运行行为。",
)

replace_block(
    r"docs\HANDOFF_CURRENT_ARCHITECTURE.md",
    "│  ├─ domain/                 # 领域模型、事件、策略和端口",
    "└─ security/               # 安全相关公共定义",
    """│  ├─ domain/                 # 领域模型、事件、策略和端口
│  ├─ application/
│  │  ├─ agent/               # Agent 会话、任务循环与运行会话控制
│  │  ├─ pet/                 # 桌宠动作、运动、状态、角色包与 Track 0 编排
│  │  └─ system/              # 开机启动、Provider profile 与启动模式
│  ├─ bootstrap/              # 生产组合根
│  ├─ infrastructure/
│  │  └─ security/            # 安全适配器（Windows Credential Manager 等）
│  ├─ presentation/qt/
│  │  ├─ pet/                 # 桌宠窗口、渲染器、overlay 与 Spine38 Qt 适配
│  │  ├─ ui/                  # 控制中心、菜单、对话框与设置控制器
│  │  └─ platform/            # 托盘、单实例与运行时桥接
│  └─ config/                 # 配置模型与加载规则""",
)

replace_exact(
    r"docs\HANDOFF_CURRENT_ARCHITECTURE.md",
    "| Schwarz 素材分发授权 | **Unknown**；素材当前在仓库外，正式发布前需法律/产品确认 |",
    "| Schwarz 素材分发授权 | **Unknown**；素材当前在仓库外，正式发布前需法律/产品确认 |\n| GPL 迁移审计 | 审计进行中：`docs/legal/gpl_migration_audit.md` 整体 gate 为 **BLOCKED**，LICENSE/README 来源声明与包元数据保持 fail-closed |",
)

replace_exact(r"docs\packaging\windows_packaging_preflight.md", "arkclaw.application.autostart_service", "arkclaw.application.system.autostart_service")
replace_exact(r"docs\packaging\windows_packaging_preflight.md", "arkclaw.presentation.qt.autostart_controller", "arkclaw.presentation.qt.ui.autostart_controller")
replace_exact(r"docs\packaging\windows_packaging_preflight.md", "arkclaw.presentation.qt.provider_settings_dialog", "arkclaw.presentation.qt.ui.provider_settings_dialog")
print("ALL P3 EDITS DONE")