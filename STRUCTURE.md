# ArkClaw 工作树结构

本文档描述 `codex/arkpets-spine-idle-vertical-slice` 第一阶段完成后的当前结构。

## 顶层目录

```text
.
├─ README.md
├─ STRUCTURE.md
├─ pyproject.toml
├─ uv.lock
├─ src/
├─ tests/
├─ dev_evidence/       # 本地测试运行证据（pytest basetemp 产物，Git 忽略）
├─ native/
├─ scripts/
├─ prototypes/
├─ docs/
├─ packaging/
└─ build/              # Git 忽略的本机构建产物
```

## 正式桌宠

正式源码位于 `src/arkclaw/`：

```text
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
```

正式 GUI 入口为：

```text
arkclaw-pet -> arkclaw.presentation.qt.pet_application:run
```

`arkclaw-pet-placeholder` 暂时保留为指向同一 composition root 的历史兼容别名。正式入口会
优先加载经过验证的 Spine role pack；配置缺失或失败时，才使用 `PlaceholderPetRenderer`。

## Spine Runtime

```text
native/spine38_bridge/
├─ include/arkclaw_spine38_bridge.h
├─ src/arkclaw_spine38_bridge.cpp
├─ tests/spine38_bridge_contract_test.cpp
├─ CMakeLists.txt
└─ spine-runtimes.lock.json
```

本地 Release DLL 位于：

```text
build/spine38/Release/arkclaw_spine38_bridge.dll
```

它是可再生成产物，不提交 Git。构建命令见 README。

## 启动与诊断脚本

```text
scripts/
├─ start_schwarz_pet.ps1       # 正式 Schwarz 启动、路径验证和 smoke
├─ build_spine38_bridge.ps1    # 构建 C++ bridge
├─ qt_*_smoke.py               # Qt 模块 smoke
├─ debug/                      # Slice 6B 本地输入/native 调试脚本
├─ test.ps1
└─ typecheck.ps1
```

`start_schwarz_pet.ps1` 是开发工作树的推荐入口。它生成本地 manifest、设置 Spine 环境变量，
并显式把当前工作树 `src` 放入 `PYTHONPATH`。

## 程序化原型

```text
prototypes/placeholder_pet/
├─ README.md
└─ start_placeholder_pet.ps1
```

这里保存强制启动程序化桌宠的独立入口。渲染实现没有复制到 `prototypes/`，因为同一个
`PlaceholderPetRenderer` 也是正式版本必要的安全 fallback；复制源码会产生两个不一致版本。

## 测试

```text
tests/
├─ unit/          # 纯应用逻辑、配置和 composition
├─ qt/            # Qt renderer、窗口和输入
├─ integration/   # 真实 Spine catalog 等集成测试
└─ fakes/
```

真实 Schwarz 测试需要外部素材、Release DLL 和本地 manifest。推荐通过：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_schwarz_pet.ps1 -Smoke
```

## 文档

```text
docs/
├─ architecture/
├─ pet/
├─ rendering/
├─ providers/
├─ packaging/
├─ legal/
├─ research/
└─ superpowers/       # 历史 spec 与实施计划
```

README 是运行和验收的首要入口；`docs/rendering/` 保存 Spine/Schwarz 的细节，
`docs/superpowers/` 保存设计过程，不作为日常启动指南。

## 工作树注意事项

- Schwarz `.skel`、`.atlas`、`.png` 保持在仓库外；
- `build/`、缓存和虚拟环境均为本地内容；
- 正式版本与原型共享单实例保护，不能同时运行；
- `PlaceholderPetRenderer` 不等于默认产品，它是原型视觉实现和生产安全 fallback；
- 不要为了“分离原型”移动正式包内的 fallback 类，否则会破坏生产故障恢复；
- 当前工作树基线（`src/arkclaw/` 完整实现）已提交。结构整理只允许移动文件并同步依赖路径，不得改变任何运行行为。
