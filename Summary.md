# ArkClaw 项目总结

> 状态：**V1 Release Candidate 1（Alpha）**
> 定位：**本地优先的 Windows 桌面 AI 同伴**（Desktop AI Companion）

## 1. 项目是什么

ArkClaw 是一个面向 Windows 10/11 的桌面产品，把「桌面上的角色」和「完整的工作界面」
统一为同一个产品、同一套 presentation state：

- **Desktop Companion（桌面伴侣）**：驻留桌面的 Active Character，提供右键
  Action Palette、左键互动/拖动、Conversation Capsule、系统托盘与安全退出。
- **Full Dashboard（完整仪表盘）**：App Shell 下的 `Home` / `Chat / Work` /
  `Character Animation` 三页导航，消费同一个权威 `ConversationContext`。

项目已经历：桌宠交互基础（Stage 9 / Slice 0–6B）→ 首个可用前端（Slice 7）→
发布候选稳定性加固（Stage 10），当前可运行、可测试、可继续迭代。

## 2. 技术栈

| 层 | 技术 |
| --- | --- |
| 语言 / 运行时 | Python 3.12 / 3.13 |
| GUI | PySide6 6.11.1（Qt） |
| 角色渲染 | Spine 3.8 C++ bridge（`native/spine38_bridge`）+ 程序化 fallback |
| 包管理 | uv（`uv.lock` 锁定） |
| 测试 | pytest 9.x（`tests/unit`、`tests/qt`、`tests/integration`、`tests/fakes`） |
| 静态检查 | ruff + mypy（strict） |
| 打包 | Nuitka 4.0（preflight 已通过，standalone 构建未授权） |

## 3. 开发阶段

### Stage 9 — Engineering Interaction Foundation（Slice 0–6B，已批准）

- **Slice 0–5A**：桌宠状态、运动、Spine 3.8 Runtime、动作调度、BODY/OVERFLOW、
  原生 hit-test、托盘、单实例、Provider 设置与安全退出基础。
- **Slice 5A-P / 5B**：`can_resume_autonomous(...)` 成为 **唯一** 权威实现；
  Action Palette 效果 sink 与 ROOT/Character/System 同壳导航成型。
- **Slice 6A（冻结）**：Action Palette 窗口策略 = `Qt.Tool | FramelessWindowHint`，
  `Qt.Popup` 正式淘汰。
- **Slice 6B**：**production cutover** —— Schwarz 右键从 native QMenu 切换到
  Action Palette；`PetApplicationCoordinator` 拥有 composition，
  `PetWindow` 只知道「请求 Palette」。

### Slice 7 — Visual Implementation / First Usable Frontend（完成）

- 按冻结的 Visual Design System v1 实现 token 层、Dashboard App Shell、
  Home、Chat / Work、Character Animation。
- Light/Dark 同一套语义 token；键盘/焦点/Reduced Motion 可验证。
- `DashboardIntegration` 懒加载唯一 Dashboard 窗口，dispose 幂等。

### Stage 10 — V1 Stabilization / Product Hardening（完成）

- 独立审查、端到端用户旅程、运行时可靠性、错误处理、性能基线、发布文档。
- 产出：`docs/release/V1_RELEASE_NOTES.md`、`V1_KNOWN_LIMITATIONS.md`、
  `V1_VALIDATION_REPORT.md`、`V1_ARCHITECTURE_STATUS.md`、`v1_performance_baseline.json`。

## 4. 已实现功能

### 桌面伴侣

- Active Character（参考素材：Schwarz）通过生产 Spine 3.8 runtime 渲染，素材失败时
  安全回退到程序化桌宠（fail-closed）。
- 右键 Schwarz → Action Palette（ROOT），同壳 Character/System 分层导航，
  Back/Escape 返回 ROOT。
- 左键 Interact、按冻结阈值拖动、下落/落地、自主动作调度。
- Conversation Capsule 绑定 **唯一** 权威 `ConversationContext`（草稿/revision/IME）。
- 系统托盘、单实例、Windows 开机启动、安全退出。

### Dashboard

- App Shell：56 px 顶栏；导航展开 208 px / 收起 72 px；页边距 40 px；内容最大 1120 px。
- Home：问候、Primary Ask、Continue Recent Work（无数据时显示显式空态）、
  Active Character 摘要、Explore。
- Chat / Work：Conversation、Task State、Activity、Result/Artifact、冻结规格 Composer
  （最大宽 800 px、圆角 24 px、IME 安全草稿）。
- Character Animation：Active Character 头、能力驱动的角色选择器、Spine 预览位
  （当前为标注占位）、能力驱动动画清单（真实 Unavailable / Trigger-unavailable 状态）。

### 可靠性 / 容错

- Agent Error 呈现于 Chat / Work，权威上下文与草稿保留，Composer 仍可跟进。
- 失败结果渲染 `Failed` + 能力驱动恢复动作；缺失 Spine 资源渲染
  `Unavailable + 原因 + Retry`。
- Dashboard 打开是纯 presentation transition：零会话、零后端任务、零应用命令。
- 懒加载 + 幂等 dispose；重开复用同一窗口。

## 5. 关键架构所有权

| 关注点 | 所有者 |
| --- | --- |
| Presentation truth / overlay / palette layer | `FrontendPresentationModel` |
| Intent 路由 / effect 应用 | `FrontendPresentationCoordinator` |
| 草稿真相 | `ConversationDraftModel`（唯一） |
| Dashboard 窗口生命周期 | `DashboardIntegration`（懒加载、幂等 dispose） |
| Resume Autonomous 有效性 | `pet_production_actions.can_resume_autonomous`（唯一） |
| 主题 token | `DesignTokens` / `QtTheme` |

## 6. 验证基线（2026-08-16）

- Stage 10 套件：**13 passed / 0 skipped**（用户旅程、运行时可靠性、错误处理）。
- 跨测试顺序：130 passed（old→new 与 new→old 均通过）。
- Broad 回归：**3407 passed**；1 个预存在的原生 smoke 失败
  （`qt_pet_opengl_backend_smoke.drag_to_falling`，此前 Slice 7 已记录）；
  27 个环境门控 skip（需要生产 manifest / bridge / native Windows）。
- Native Windows 门（6A + 6B + Schwarz 合并）：**19 passed / 0 skipped**，单进程 exit 0。
- `qt_pet_smoke` exit 0；`qt_tray_smoke` exit 0。
- 性能基线：Dashboard 冷开 ~13 ms、暖重开 ~0.3 ms；100 轮开/关循环内存平稳
  （见 `docs/release/v1_performance_baseline.json`）。

## 7. 已知限制（V1 不包含）

- Dashboard 提交为 inert snapshot，不触发真实 backend/provider 执行。
- Dashboard Spine 预览为占位表面，未绑定真实 Spine presentation seam。
- 附件上传为 presentation 级状态，无真实上传传输。
- 无扩展 IA：没有 Materials/Projects/Tools/Models/Plugins/History，Settings 不是一级页。
- 详情见 `docs/release/V1_KNOWN_LIMITATIONS.md`。

## 8. 工程卫生（本轮整理）

- 根目录 pytest 测试证据已归入 `dev_evidence/`（`.pytest_tmp_*`，Git 忽略）。
- Slice 6B 调试脚本已归入 `scripts/debug/`。
- 真实测试代码保持在标准结构：`tests/unit`、`tests/qt`、`tests/integration`、`tests/fakes`。

## 9. 文档导航

- `README.md` — 产品定位、启动方式、License
- `STRUCTURE.md` — 目录结构
- `docs/release/` — V1 发布文档与验证报告
- `docs/legal/gpl_migration_audit.md` — License 迁移审计（当前 BLOCKED）
- `docs/engineering/`、`docs/design/`、`docs/product/` — 工程与设计契约