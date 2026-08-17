from pathlib import Path

p = Path(r"D:\ArkClaw\docs\engineering\repository-architecture-review.md")
raw = p.read_text(encoding="utf-8")
nl = "\r\n" if "\r\n" in raw else "\n"
lines = raw.splitlines()

anchor = "> 本阶段只新增本文件，不修改任何生产代码，不移动任何核心源文件。"
idx = next(i for i, l in enumerate(lines) if anchor in l)
top_note = [
    ">",
    "> **状态更新（2026-08-14，结构整理已执行）**：本文件正文（§1–§16）为**重构前审计快照**，",
    "> 描述 `src/sjtuclaw/` 时代的仓库事实。审计后的结构整理已执行完毕并通过回归验证，",
    "> 当前仓库结构、迁移记录与验证结果见 **§17 Post-Refactor Execution Record**。",
]
lines[idx + 1 : idx + 1] = top_note

s = nl.join(lines)
old_label = "以下为整理后的当前目录树"
assert s.count(old_label) == 1, "tree label not found"
s = s.replace(old_label, "以下为审计时（重构前）的目录树快照")
lines = s.split(nl)

app_idx = next(i for i, l in enumerate(lines) if l.startswith("## Appendix A"))

section17 = """## 17. Post-Refactor Execution Record

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

"""
lines[app_idx:app_idx] = section17.splitlines()
out = nl.join(lines)
p.write_text(out, encoding="utf-8")
print("review doc updated; lines:", len(lines), "newline:", "CRLF" if nl == "\r\n" else "LF")