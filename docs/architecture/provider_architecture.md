# Provider 与凭据架构

## 四类标识

ArkClaw 明确区分以下概念：

- `ProviderId`：适配器实现的稳定注册标识，例如 `openai`、`deepseek`。
- `ApiProtocol`：实际 wire/API 语义，例如 Responses 或 Chat Completions。
- `ProviderProfile`：非敏感配置，绑定 Provider、协议、模型、固定服务 Origin、
  capabilities 与一个可选 CredentialId。
- `CredentialId`：凭据存储键；它是 opaque identifier（不透明标识），不是
  Provider 名、模型名、URL 或 API Key。
- `CredentialBinding`：权威的非敏感元数据，把一个 CredentialId 限定到一个
  ProviderId 和一个固定 HTTPS Origin。

这些类型不能互换。尤其是“使用统一 SecretStore”不等于“任意厂商的 API Key
可以调用任意 Provider”。API Key 必须由目标服务签发，并由 Profile 显式绑定。

## CredentialId 与 Windows Target

`SecretStore` 提供通用的 `has_secret()`、`get_secret()`、`set_secret()` 和
`delete_secret()`。已有的 OpenAI 专用方法继续存在，并始终代理到保留的 OpenAI
CredentialId，以保持调用兼容性。

Windows Target 解析规则是封闭的：

| CredentialId | Target |
|---|---|
| 保留 OpenAI ID | `ArkClaw/OpenAI/APIKey` |
| 内置 DeepSeek UUIDv4 | `ArkClaw/Credentials/00000000-0000-4000-8000-000000000001` |
| canonical UUIDv4 | `ArkClaw/Credentials/<uuid>` |

除了保留 ID 外，只接受由应用生成或严格校验的 canonical UUIDv4。显示名称、模型、
ProviderId、URL 和其他动态文本永远不参与 Target 生成。这避免路径注入、Target
别名和凭据串用。

生产 `CredentialTargetResolver` 对两个人工验证 CredentialId 固定 fail-closed，
并在任何 Credential Backend 调用前拒绝；它们不会退化为通用 UUID Target。
两个人工验证脚本使用 `scripts/manual_credential_targets.py` 中显式注入的封闭
Resolver。该 Resolver 只接受两个固定的人工 CredentialId，不能接收任意 Target
字符串，也不从 argv、环境变量、URL 或用户输入构造 Target。

API Key 不进入 `RuntimeConfig`、CLI 参数、普通配置序列化、SQLite 或自动环境变量
读取逻辑。`EnvironmentSecretStore` 的既有 `OPENAI_API_KEY` 行为仅作为显式注入的
向后兼容开发入口，不是 Provider 失败时的回退来源。

## CredentialBinding

SecretStore 只保存 SecretValue，不保存绑定描述。`CredentialBindingRegistry`
由 Composition Root/ProviderFactory 持有。通用校验集中在
`ProviderRegistry.build()`，并在调用任何 Builder 之前执行精确检查：

```text
profile.credential_id
  → CredentialBinding
  → binding.provider_id == profile.provider_id
  → binding.allowed_origin == profile.origin
  → Provider Builder
```

默认 OpenAI 凭据只允许 `openai + https://api.openai.com`；默认 DeepSeek 凭据只允许
`deepseek + https://api.deepseek.com`。绑定不存在、Provider 不同或 Origin 不同
都会在 `SecretStore.get_secret()` 和 Client 创建前失败。
因此，即使自定义 Registry 注入了遗漏校验的 Builder，也不能绕过这一基础边界；
内置 Builder 的重复检查仅作为纵深防御。`credential_id=None` 的 Fake/Ollama 等
无凭据 Profile 不执行 CredentialBinding 校验。

同一个 Provider 可以注册多个 CredentialBinding，但每个 CredentialId 只有一条
权威绑定。即使两个服务实际使用相同的字符串，也必须分别创建两个 CredentialId
并分别保存，不能让一个绑定跨 Provider 共享。

`builtin_credential_bindings()` 只注册生产 OpenAI 与 DeepSeek Binding。人工验证
Binding 不进入默认 `ProviderFactory`；DeepSeek 人工脚本必须显式构造其脚本专用
Registry。生产 Profile Policy 对人工 CredentialId 的拒绝仍作为纵深防御保留。

## Profile 与注册表

`ProviderRegistry` 使用 `(ProviderId, ApiProtocol)` 精确查找 Builder。注册重复、
Profile 被禁用或没有精确 Builder 时都会固定失败：

```text
ProviderProfile
  → exact (ProviderId, ApiProtocol)
  → one registered builder
  → one provider instance
```

系统不会因为凭据缺失、协议不支持或 Provider 不可用而切换到其他 Provider。
ProviderFactory 中保留少量 RuntimeConfig 兼容分派，但实际构造统一经过注册表；
新增 Provider 不需要修改 AgentLoop 或 ContextManager。

内置 OpenAI 和 DeepSeek Builder 还会验证审查过的 ProviderId、协议、CredentialId
与固定官方 Origin。修改 Profile 的 `base_url` 不能把内置适配器变成任意
OpenAI-compatible 代理。

## Capability 与 continuation

Adapter/Builder 是真实能力的权威来源。`ProviderCapabilities.streaming` 只表示
Adapter 是否支持流式传输，不能由 Profile 改写；Profile 的 streaming 字段必须
与 Adapter 声明完全一致。`RuntimeConfig.stream` 则是本次 Provider 实例的运行
开关，不会改变 `capabilities().streaming`。

其他可限制能力仍按以下规则计算：

```text
effective_non_streaming_capabilities =
adapter_maximum_capabilities ∩ profile_requested_restrictions
```

Profile 不能把 Adapter 的 `tools=False` 提升为 `True`，也不能伪造 protocol 或
continuation mode；也不能把 `streaming=True` 改成虚假的 `False`。构造失败发生
在凭据读取和请求发送前。DeepSeek 当前只实现流式调用，因此实例运行开关为
`stream=False` 时会在读取凭据和创建 Client 前返回 `unsupported_capability`，
但其 Adapter 能力仍准确报告 `streaming=True`。OpenAI 与 DeepSeek 对 streaming
字段采用相同定义。

| Provider | 协议 | continuation | tools |
|---|---|---|---|
| Fake | internal | replay messages | 否 |
| OpenAI | Responses | replay provider items | 是 |
| DeepSeek | Chat Completions | replay messages | 否 |

Continuation 是 Provider 专属状态，不能跨 Provider 或协议复用。DeepSeek
continuation 还绑定 ProfileId 和适配器版本；绑定不匹配时在读取凭据和创建 Client
之前失败。

## 当前边界

当前基础架构允许多个 Profile 分别绑定不同 CredentialId，但尚未提供 GUI Profile
编辑器、任意第三方兼容端点或用户自定义协议适配器。支持新的云服务应新增经过审查的
协议适配器和 Builder，而不是把服务 URL、密钥或协议差异塞进一个通用 Provider。

版本化 JSON Repository、CredentialBinding 引用和活动 Provider 切换规则见
[Provider Profile 元数据管理](provider_profile_management.md)。CLI、未来 Qt 与
Gateway 应通过同一个 `ProviderProfileService` 管理这些元数据，不得直接修改
JSON。
