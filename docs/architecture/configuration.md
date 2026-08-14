# ArkClaw 配置系统

配置系统只管理非敏感运行参数。`RuntimeConfig` 是经过校验的不可变快照，创建后
不允许原地修改。

## 配置字段

| 字段 | 默认值 | 环境变量 | CLI 参数 |
|---|---:|---|---|
| `provider` | `fake` | `ARKCLAW_PROVIDER` | `--provider` |
| `openai_model` | `gpt-5-mini` | `ARKCLAW_OPENAI_MODEL` | `--openai-model` |
| `deepseek_model` | `deepseek-v4-flash` | `ARKCLAW_DEEPSEEK_MODEL` | `--deepseek-model` |
| `ollama_model` | `qwen3` | `ARKCLAW_OLLAMA_MODEL` | `--ollama-model` |
| `provider_timeout_seconds` | `30` | `ARKCLAW_PROVIDER_TIMEOUT_SECONDS` | `--provider-timeout-seconds` |
| `max_turn_seconds` | `90` | `ARKCLAW_MAX_TURN_SECONDS` | `--max-turn-seconds` |
| `openai_max_retries` | `2` | `ARKCLAW_OPENAI_MAX_RETRIES` | `--openai-max-retries` |
| `deepseek_max_retries` | `0` | `ARKCLAW_DEEPSEEK_MAX_RETRIES` | `--deepseek-max-retries` |
| `ollama_base_url` | `http://127.0.0.1:11434` | `ARKCLAW_OLLAMA_BASE_URL` | `--ollama-base-url` |
| `max_output_tokens` | `1024` | `ARKCLAW_MAX_OUTPUT_TOKENS` | `--max-output-tokens` |
| `stream` | `true` | `ARKCLAW_STREAM` | `--stream` / `--no-stream` |

OpenAI、DeepSeek 和 Ollama 分别保存模型名称，不共用一个全局模型字段。

## 超时边界

两个超时解决不同层次的问题：

- `provider_timeout_seconds`：留给未来 OpenAI/Ollama 适配器，限制一次 HTTP
  请求、连接或流读取操作。当前 Fake Provider 不使用该字段。
- `max_turn_seconds`：由 `AgentLoop` 使用，限制包含上下文构建、Provider 流和
  Agent 状态转换在内的整个用户回合。

总回合超时通常应大于单次 Provider 请求超时。二者可以独立配置，且都必须是有限
正数。

## 覆盖优先级

配置来源从高到低为：

```text
CLI 参数
  > 环境变量
  > 应用设置
  > 程序默认值
```

应用设置使用与 `RuntimeConfig` 相同的字段名，通过映射传给 `ConfigLoader`。
当前阶段没有设置文件，也不会把配置写入数据库。

## CLI 示例

使用默认 Fake Provider：

```powershell
.\.venv\Scripts\arkclaw-agent-demo.exe
```

关闭 Fake Provider 的分块输出，但仍使用统一事件协议：

```powershell
.\.venv\Scripts\arkclaw-agent-demo.exe --no-stream
```

人工运行 OpenAI Provider：

```powershell
.\.venv\Scripts\arkclaw-agent-demo.exe --provider openai
```

该命令会读取固定 Windows Credential Manager Target，并在凭据存在时发起真实
 OpenAI API 请求。因此它不属于自动测试或本阶段的安全验证命令。Ollama 仍会明确
报告尚未实现。

选择 DeepSeek Provider：

```powershell
.\.venv\Scripts\arkclaw-agent-demo.exe --provider deepseek
```

该入口只使用内置 DeepSeek Profile：Chat Completions 协议、固定官方 Origin
`https://api.deepseek.com` 和独立的 DeepSeek CredentialId。它不会接受任意
`base_url`，也不会回退到 OpenAI 或其他 Provider。默认离线测试使用 Fake SDK，
不会执行此真实网络路径。该普通对话入口不是受控真实验证入口；人工验证只能使用
`scripts/manual_deepseek_verification.py`，具体边界见
[DeepSeek Provider](../providers/deepseek_provider.md)。

## API Key 边界

`RuntimeConfig` 不包含 API Key。项目也没有提供 `--api-key` 参数或
`ARKCLAW_OPENAI_API_KEY` 普通配置字段。

凭据由独立的、Provider-neutral（厂商无关）的 `SecretStore` 处理。公共操作使用
不透明且经过校验的 `CredentialId`；旧的 OpenAI 专用方法保留为兼容外观：

- `InMemorySecretStore`：自动测试使用，不持久化。
- `EnvironmentSecretStore`：仅在调用方显式注入时从进程的 `OPENAI_API_KEY`
  读取开发凭据，不能保存或删除环境变量。
- `WindowsCredentialSecretStore`：通过 Windows Credential Manager 保存桌面应用
  使用的 Generic Credential。

API Key 不得写入 SQLite、设置文件、`.env`、日志、异常信息或配置序列化结果。
`SecretValue` 的 `str` 和 `repr` 始终显示为 `<redacted>`，只有调用 `reveal()` 时
才会显式取得原始值。

内置凭据的 Windows Credential Target 固定为：

```text
ArkClaw/OpenAI/APIKey
ArkClaw/Credentials/00000000-0000-4000-8000-000000000001
```

应用创建的 CredentialId 必须是 canonical UUIDv4，并只映射到
`ArkClaw/Credentials/<uuid>`。显示名称、Provider 名、模型名、服务 URL 和其他
用户输入均不能参与 Target 拼接。空值、路径片段、超长值或非 UUID 值会在进入
Backend 前被拒绝。

生产 Resolver 不包含人工验证 Target，并对两个人工验证 CredentialId 固定拒绝，
拒绝发生在 Backend 的 read/write/delete 之前。固定人工 Target 只存在于
`scripts/manual_credential_targets.py`，由人工验证脚本和显式跳过的集成测试注入；
普通 Profile、默认 ProviderFactory 和 Qt 设置服务不能选择该 Resolver。

“厂商无关”表示同一个安全存储接口可以保存多个 Provider 的凭据，并不表示一个
厂商签发的 API Key 能在另一个厂商使用。Provider Profile 会绑定一个明确的
CredentialId，OpenAI 与 DeepSeek 的保留凭据互不别名、互不回退。

`WindowsCredentialSecretStore` 依赖可注入的
`CredentialBackend`，因此默认 pytest 使用 Fake Backend，不会访问用户的真实
Credential Manager。Windows 访问拒绝、后端不可用、凭据损坏和未知系统错误会被
映射为明确且不包含密钥的 `SecretStoreError`。公共 Store 边界不会把原始 Backend
异常、`UnicodeDecodeError` 或 `UnicodeEncodeError` 保留为异常的 cause/context，
避免 traceback 和 `logger.exception()` 重新输出敏感异常正文。

在 Windows 上只检查凭据是否存在、而不显示凭据：

```powershell
.\.venv\Scripts\python.exe -c "from arkclaw.infrastructure.security.windows_credential_store import WindowsCredentialSecretStore; print(WindowsCredentialSecretStore().has_openai_api_key())"
```

没有 `--api-key <plaintext>` 参数，因为命令行参数可能进入 PowerShell 历史和进程
列表。`EnvironmentSecretStore` 也不会被自动选择或作为 Windows 后端失败时的静默
回退。只有显式选择 OpenAI Provider 并开始请求时才会读取凭据。

Python 无法可靠保证字符串对象的内存擦除。实现只减少密钥副本和生命周期，并禁止
将 CredentialBlob、Authorization Header 或 `SecretValue.reveal()` 结果写入日志；
不宣称提供了安全内存清零。

### 人工启用的 Windows 集成验证

默认 pytest 不访问 Credential Manager。需要在测试机上人工验证 Win32 读写时，
可以显式启用仅操作固定测试 Target `ArkClaw/Test/OpenAI/APIKey` 的集成测试：

```powershell
$env:ARKCLAW_RUN_WINDOWS_CREDENTIAL_INTEGRATION = "1"
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider tests\integration\test_windows_credential_store_integration.py
Remove-Item Env:ARKCLAW_RUN_WINDOWS_CREDENTIAL_INTEGRATION
```

测试在进程内生成假密钥，不从命令行读取密钥，不访问网络，并在 `finally` 中删除
测试 Target。它显式注入脚本专用 Resolver，绝不使用生产 Target
`ArkClaw/OpenAI/APIKey`。该测试仍默认跳过。

## Provider 当前状态

| Provider | 当前状态 |
|---|---|
| Fake | 已实现；支持分块或整段 `TextDelta`，随后发送 `Completed` |
| OpenAI | 已实现；Responses API、流式文本、函数调用解析和本地 continuation |
| DeepSeek | 已实现纯文本流；固定官方 Chat Completions Origin，不开放工具调用 |
| Ollama | 配置名称与服务地址已保留；Provider 尚未实现 |

无论 `stream` 是否开启，`AgentLoop` 始终只处理统一的 `LLMEvent`：

```text
stream=true:
TextDelta → TextDelta → Completed

stream=false:
TextDelta（完整文本）→ Completed
```

CLI 创建并持有 Provider，在 CLI 退出时调用其幂等 `aclose()`。每个 Agent 回合只
关闭本回合的事件流，不关闭整个 Provider。合法 `Completed` 可以附带与 Provider
名称绑定的内存态 continuation；失败、超时、取消或 Provider 切换不会提交不匹配
的 continuation。

OpenAIProvider 的请求固定包含 `store=False`，即使外部 `LLMRequest.store=True`
也不会启用服务端响应保存。Provider 每次请求前重新读取 `SecretStore`：密钥删除
后不会创建 SDK 请求，密钥变化会关闭旧 Client 和旧流，再创建新 Client。API Key
只在创建 SDK Client 的短暂调用路径中显式揭示；Python 无法保证不可变字符串的
可靠内存擦除。

多轮 continuation 不使用 `previous_response_id` 作为唯一状态，而是将已确认的
本地输入历史和完整响应 `output` 项以确定性 JSON 编码保存在内存中。下一轮会验证
消息指纹、跳过调用方重复附加的 assistant 文本，并重放 Provider 专属输出项。
设计依据和限制见 [OpenAI Provider](../providers/openai_provider.md)。

多 Provider 的标识、Profile、CredentialId、注册表与无回退约束见
[Provider 架构](provider_architecture.md)。DeepSeek 的请求映射、流终止语义、
continuation 和当前能力限制见 [DeepSeek Provider](../providers/deepseek_provider.md)。

未来设置发生变化时，应重新执行：

```text
保存新设置
→ ConfigLoader 创建新的 RuntimeConfig
→ ProviderFactory 创建新的 Provider
→ 将新 Provider 交给 Agent Runtime
```

不得让多个线程同时修改一个全局可变配置对象。
