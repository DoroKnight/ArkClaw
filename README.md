# SJTUClaw

SJTUClaw 是一个以 Windows 为首要平台的 2D AI 桌宠项目。目前，项目已经完成
Agent Runtime 的第一个开发里程碑：核心 Agent 循环不依赖 GUI、云端凭据或
外部服务即可运行。

## 本阶段已经实现

- 与具体框架无关的领域模型和事件类型。
- `LLMProvider`、记忆仓库、工具权限和提醒调度等端口接口。
- 支持流式输出且结果确定的 `FakeProvider`。
- 规模受限、行为可预测的 `ContextManager`。
- 支持状态事件、超时、取消、Provider 错误处理的 `AgentLoop`。
- 可复用且具有显式异步关闭契约的 Provider 生命周期。
- 相互独立的 Provider 请求超时与 Agent 总回合超时。
- 不向应用层泄露 SDK 类型的 Provider continuation 状态传递。
- 对尚未支持的工具调用采用安全失败关闭（fail-closed）策略。
- 单元测试和用于开发验证的命令行演示程序。

当前 Runtime 不会执行任何工具。如果 Provider 返回工具调用请求，Agent 会安全地
拒绝执行。后续只有在接入 `ToolService`、权限策略和用户确认界面后，才会开放经过
授权的工具调用。

Agent 的 `max_turn_seconds` 在直接构造和配置加载两条路径上都会拒绝布尔值、
NaN、Infinity、零和负数。

## 环境要求

- Python 3.12 或 3.13
- Windows PowerShell

本阶段的 Agent Runtime 不依赖第三方运行时库。Ruff、mypy 和 pytest 仅作为开发
依赖安装。

## 创建开发环境

```powershell
uv sync --extra dev
```

该命令会根据 `pyproject.toml` 和 `uv.lock` 创建 `.venv` 虚拟环境，并安装项目及
开发工具。

## 运行测试

```powershell
.\.venv\Scripts\python.exe -m pytest
```

## 运行 Agent 演示

```powershell
.\.venv\Scripts\sjtuclaw-agent-demo.exe
```

输入任意消息后，可以观察 Fake Provider 的流式回复。输入 `/quit` 或 `/exit`
结束程序。

`scripts/` 目录中的脚本只是便捷入口，并不是运行项目的必要条件。如果 Windows
禁止执行本地 PowerShell 脚本，可以使用以下方式运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File <脚本路径>
```

也可以直接使用前面给出的虚拟环境命令。

## 配置

Agent 启动参数由不可变的 `RuntimeConfig` 统一管理，覆盖优先级为：

```text
CLI 参数 > 环境变量 > 应用设置 > 程序默认值
```

当前可选择 `fake`、`openai`、`deepseek` 和 `ollama`。Fake Provider、
OpenAI Responses API Provider 与 DeepSeek Chat Completions 纯文本 Provider
已实现；Ollama 仍会返回明确的“尚未实现”错误，不会静默回退。

`provider_timeout_seconds` 是 OpenAI SDK 的单次 HTTP 请求或流读取超时；
`max_turn_seconds` 是 Agent 从接收用户消息到结束整个回合的总时间上限。当前
Fake Provider 不使用请求超时，`AgentLoop` 只使用独立的总回合超时。

配置字段、默认值、环境变量、CLI 参数和 API Key 安全边界详见
[配置系统文档](docs/configuration.md)。

## API Key 凭据

API Key 不属于 `RuntimeConfig`，也没有 `--api-key` 命令行参数：

- `EnvironmentSecretStore` 仅供显式注入的本地开发场景使用，不会被自动选择。
- `WindowsCredentialSecretStore` 使用 Windows Credential Manager 的 Generic
  Credential；内置 OpenAI 与 DeepSeek 分别使用固定且互不别名的 Target。
- `InMemorySecretStore` 仅用于自动测试或临时进程内状态。

通用 SecretStore 可以保存多个 Provider 的凭据，但 API Key 仍必须由所选服务商
签发，不能把 DeepSeek Key 当作 OpenAI Key 使用。应用生成的额外 CredentialId
使用 UUIDv4；显示名、模型名和 URL 不参与 Windows Target 拼接。

默认自动测试注入 Fake Credential Backend，不会读取、修改或删除用户的真实
Credential Manager 数据。需要检查是否已经保存凭据时，可以只查询布尔状态：

```powershell
.\.venv\Scripts\python.exe -c "from sjtuclaw.infrastructure.security.windows_credential_store import WindowsCredentialSecretStore; print(WindowsCredentialSecretStore().has_openai_api_key())"
```

该命令不会打印密钥。不要把明文密钥作为 PowerShell 参数；后续应通过 `getpass`
或 Qt Provider 设置界面录入。显式运行 `--provider openai` 会读取该固定 Target，并在
凭据存在时创建真实 OpenAI 请求；自动测试只注入 Fake SDK，绝不执行该路径。

## Qt 桌面壳

安装可选 GUI 依赖后，可启动普通的最小桌面窗口：

```powershell
uv sync --extra dev --extra gui
.\.venv\Scripts\sjtuclaw-gui.exe
```

启动只初始化非敏感 Profile 元数据，不会自动读取凭据、激活云端 Provider 或发送
网络请求。Provider 设置页只显示“已配置/未配置”，不会回填已保存的 API Key。
当前窗口不包含透明、置顶、托盘或动画桌宠效果。对象所有权、异步关闭和设置命令
边界见 [Qt Provider 设置壳文档](docs/qt_provider_settings_shell.md)。

原创程序化占位桌宠可通过下列命令单独启动：

```powershell
.\.venv\Scripts\sjtuclaw-pet-placeholder.exe
```

该入口安装为 Windows GUI launcher，不创建额外控制台窗口。控制台版
`sjtuclaw-agent-demo.exe` 继续保留标准输入输出。

它使用透明无边框窗口、可替换 QPainter Renderer、分层动画/行为状态机与现有
安全关机流程，并提供程序化图标的最小系统托盘；不包含正式角色素材或 Spine
Runtime。详见[占位桌宠窗口文档](docs/pet_window_placeholder.md)和
[系统托盘文档](docs/system_tray.md)。

## 架构约束

`domain` 和 `application` 包不得导入 PySide6、OpenAI、Ollama 或 SQLite。
这样可以保证核心 Agent 逻辑不依赖具体 GUI、模型服务商或数据库。

具体实现应按照以下规则放置：

- OpenAI、DeepSeek、Ollama、Fake Provider 等适配器放在 `infrastructure/llm/`。
- SQLite 等持久化实现放在 `infrastructure/persistence/`。
- 工具和权限实现放在 `infrastructure/tools/`。
- PySide6 窗口、控件和 Runtime Bridge 放在 `presentation/qt/`。

这一约束使 Agent 核心可以在没有桌面界面的情况下独立测试，也便于后续替换
Provider、数据库或 GUI 实现。

命令行 Composition Root 创建并最终关闭 Provider。`AgentLoop` 每个回合只关闭
该回合的异步事件流，因此同一 Provider 可以安全地用于后续回合。Provider
continuation 只在合法完成事件后提交；切换 Provider 时，名称不匹配的 continuation
会被拒绝。

OpenAIProvider 始终显式发送 `store=False`。多轮状态采用内存中的本地重放历史，
不会仅依赖服务端 `previous_response_id`；完整设计见
[OpenAI Provider 文档](docs/openai_provider.md)。

多 Provider 的类型、Profile、凭据隔离和无回退规则见
[Provider 架构文档](docs/provider_architecture.md)；DeepSeek 的固定官方 Origin、
能力限制、流终止语义与资源生命周期见
[DeepSeek Provider 文档](docs/deepseek_provider.md)。

DeepSeek 的真实兼容性检查不得使用普通 `--provider deepseek` 对话入口替代。
专用脚本 `scripts/manual_deepseek_verification.py` 默认完全惰性；只有用户单独确认
费用、测试 Target 和协作式超时风险后，才允许显式启用。当前阶段没有执行真实
DeepSeek API 验证。
