from pathlib import Path
wt = Path(r"D:\ArkClaw\.worktrees\arkpets-spine-idle-vertical-slice")

# --- STRUCTURE.md: replace the src/arkclaw/ fenced block ---
p = wt / "STRUCTURE.md"
text = p.read_text(encoding="utf-8")
lines = text.splitlines(keepends=True)
start = None
for i, l in enumerate(lines):
    if l.rstrip("\r\n") == "```text" and i + 1 < len(lines) and "src/arkclaw/" in lines[i + 1]:
        start = i
        break
assert start is not None, "src/arkclaw fenced block not found"
end = None
for i in range(start + 1, len(lines)):
    if lines[i].rstrip("\r\n") == "```":
        end = i
        break
assert end is not None, "closing fence not found"
nl = "\r\n" if lines[start].endswith("\r\n") else "\n"
new_block = """```text
src/arkclaw/
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
└─ config/
```"""
new_lines = [b + nl for b in new_block.split("\n")]
lines[start : end + 1] = new_lines
p.write_text("".join(lines), encoding="utf-8")
print("STRUCTURE.md fenced block replaced")

# --- STRUCTURE.md: stale note ---
s = p.read_text(encoding="utf-8")
old_note = "当前工作树包含第一阶段实现的未提交改动，整理时不得丢弃或覆盖这些改动。"
new_note = "当前工作树基线（`src/arkclaw/` 完整实现）已提交。结构整理只允许移动文件并同步依赖路径，不得改变任何运行行为。"
assert s.count(old_note) == 1, "note not found exactly once"
p.write_text(s.replace(old_note, new_note), encoding="utf-8")
print("STRUCTURE.md note updated")

# --- HANDOFF: remove leftover top-level security line ---
p = wt / r"docs\HANDOFF_CURRENT_ARCHITECTURE.md"
s = p.read_text(encoding="utf-8")
leftover = "│  └─ security/               # 安全相关公共定义\r\n"
if s.count(leftover) == 1:
    s = s.replace(leftover, "")
elif s.count(leftover.replace("\r\n", "\n")) == 1:
    s = s.replace(leftover.replace("\r\n", "\n"), "")
else:
    raise AssertionError("leftover security line not found")
p.write_text(s, encoding="utf-8")
print("HANDOFF leftover security line removed")