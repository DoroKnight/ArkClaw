# DeepSeek Provider

## 定义与固定边界

`DeepSeekProvider` 是独立的 Chat Completions 文本流适配器，不复用
`OpenAIProvider` 的 Responses 状态机。它只允许内置 Profile：

- ProviderId：`deepseek`
- ApiProtocol：`chat_completions`
- Origin：`https://api.deepseek.com`
- 默认模型：`deepseek-v4-flash`
- Credential Target：`ArkClaw/Credentials/00000000-0000-4000-8000-000000000001`

Origin 是代码中的固定值，不是 CLI、环境变量或用户 Profile 输入。底层复用固定
版本 OpenAI Python SDK 的 Chat Completions 客户端类型，只是传输边界实现选择，
不代表 DeepSeek 与 OpenAI Provider、凭据或协议状态机相同。

模型名称和服务可用性可能变化。当前默认值依据实现时的 DeepSeek 官方文档；真实
运行前仍需用户检查官方模型、价格与服务状态：

- [DeepSeek API Docs](https://api-docs.deepseek.com/)
- [Create Chat Completion](https://api-docs.deepseek.com/api/create-chat-completion)

本阶段没有执行真实 DeepSeek API 验证。

## 请求映射

Provider 将统一请求映射为：

- instructions → 第一条 `system` message；
- memory context → 带 `untrusted_memory_data` 标记的 `user` message；
- 普通 messages → 对应 Chat Completions role/content；
- `max_output_tokens` → `max_tokens`；
- `stream=True`；
- `extra_body={"thinking": {"type": "disabled"}}`。

当前只实现纯文本。工具定义、tool role、embeddings、非流式模式以及其他未声明能力
都会 fail closed，并且在读取凭据或创建 SDK Client 前返回
`unsupported_capability`。

`ProviderCapabilities.streaming` 表示 Adapter 支持流式传输，不是实例开关。
Profile 不能把该字段从 `True` 改为 `False`；`RuntimeConfig.stream` 才控制本次
实例是否启用流式调用，且不会改写 `capabilities()`。当前 DeepSeek Adapter 只实现
流式调用，所以 `RuntimeConfig.stream=False` 会在凭据读取和 Client 创建前安全
失败。

DeepSeek V4 当前默认启用 thinking。文本版 Adapter 因为不展示、保存或重放
`reasoning_content`，所以必须显式关闭 thinking；它也不会发送
`reasoning_effort`。该参数由窄类型 `ThinkingMode.DISABLED` 固定，不来自 Profile
的任意 `extra_body`。如果未来开放 thinking，需要单独重新设计预算、展示、
continuation 和持久化边界。

- [Thinking Mode](https://api-docs.deepseek.com/guides/thinking_mode)

## 流与终止语义

普通文本 delta 转换为 `LLMEvent.text_delta()`。空 delta、role-only chunk 和
usage-only chunk 作为 metadata 忽略；`reasoning_content` 在 SDK 适配边界丢弃，
不会进入领域事件、continuation、日志或用户输出。

终止原因使用固定映射：

| finish_reason | 结果 |
|---|---|
| `stop` | 完成 |
| `length` | `output_budget_exhausted` |
| `content_filter` | `content_filtered` |
| `tool_calls` | `unsupported_capability` |
| `insufficient_system_resource` | `provider_unavailable` |
| 未知值 | `invalid_response` |

完成必须同时满足：收到 `stop`、至少出现一段非空可见文本、Stream 成功关闭。
缺少终止、空响应、重复/终止后业务事件或资源关闭失败都不能提交 `Completed`。

## continuation

DeepSeek 使用本地 replay-messages continuation。状态只包含受控元数据：

- adapter version；
- ProfileId；
- ApiProtocol。

它不保存响应正文、reasoning、API Key 或服务端对象。下一轮仍由上层传入规范化历史
消息；Provider 只验证 continuation 确实属于同一个 Profile、协议和适配器版本。
跨 Profile、跨 Provider、跨协议、非法 UTF-8/JSON 或字段不精确匹配都会在任何
凭据读取和 SDK 创建之前失败。

## 凭据轮换与资源关闭

Provider 每次请求前按 Profile 的 CredentialId 读取 SecretStore，并只缓存
SHA-256 指纹用于检测轮换：

- 缺少凭据：不创建 Client；
- 凭据变化：先关闭旧 Client/Stream，再创建新 Client；
- 删除凭据：关闭旧资源且不创建请求；
- CancelledError：原样传播；
- Stream/Client 关闭失败：保留在 pending registry，阻断新请求并在后续显式重试。

`lifecycle_lock` 只覆盖 pending cleanup、凭据轮换、Client 创建/发布、Stream
注册/退休和 `aclose()`，不会覆盖完整 SSE 消费或向调用者 `yield`。活动 Stream
保存在字典中，因此相同凭据的多个请求可以并发消费。`aclose()` 先标记 closed，
隔离当前 Client 和全部活动 Stream，再主动关闭；关闭或取消后状态不确定的资源留在
pending/closing 集合中，重复 `aclose()` 会继续清理。

实现不会启动后台清理 Task。离线测试使用 Fake SDK 与 Fake SecretStore，验证取消、
并发 Stream、凭据轮换、关闭失败重试、错误脱敏与无遗留 Task；默认 pytest 不访问
网络或真实 Windows Credential Manager。

## DeepSeek 专用人工验证入口

`scripts/manual_deepseek_verification.py` 是独立的受控入口。普通
`--provider deepseek` 不是验证入口。无参数执行只输出：

```text
safe_code=manual_verification_disabled
```

无参数路径不构造 Store/Client，不调用 input/getpass，也不访问网络或 Credential
Manager，并以退出码 0 表示预期的安全惰性状态。提供 `--confirm-real-api` 但确认
失败、验证开始后的任何检查或清理失败均返回退出码 2；只有全部验证成功才返回 0。
真实入口必须由用户明确接受费用与协作式超时风险后亲自在 Windows
PowerShell 中运行：

```powershell
.\.venv\Scripts\python.exe .\scripts\manual_deepseek_verification.py --confirm-real-api
```

随后必须精确输入 `RUN`，并通过隐藏输入提供专用测试 API Key。密钥不接受 CLI
参数或环境变量。入口固定：

- Origin：`https://api.deepseek.com`
- Model：`deepseek-v4-flash`
- Protocol：Chat Completions
- thinking：disabled
- `stream=True`
- `max_retries=0`
- 每次最多 256 output tokens
- 单请求 SDK timeout：60 秒
- 协作式整体 timeout：600 秒
- 固定测试 Target：`ArkClaw/Test/DeepSeek/APIKey`

600 秒不是进程级硬截止。`asyncio.wait_for()` 到时会请求取消，并等待取消传播及
finally 清理完成；同步阻塞或不响应取消的 SDK/系统调用可能使实际时间超过 600 秒。
持续阻塞时用户可能需要人工终止，随后必须检查测试 Target。

真实 delegate 调用计划最多六次：基础文本、message replay、首个 text delta 后
取消、取消后复用、无效测试密钥映射、恢复密钥后成功。第七次探测由本地 Audit
边界在 delegate 前拒绝；删除密钥后的 `missing_api_key` 检查也不能创建请求。
本地计数不证明请求是否到达服务器，也不是计费保证。

Target 使用 SHA-256 指纹和常量时间比较实现值级所有权。初始占用、隐藏输入期间
被占用或所有权丢失时，不覆盖、不删除外部值，也不创建 Client。finally 只清理
本轮仍然拥有的值，并在删除后重新读取确认不存在。如果本轮删除后外部程序重新写入
Target，入口不会再次删除该外部值，而是返回
`safe_code=test_target_ownership_lost`。普通删除失败返回
`safe_code=target_cleanup_failed`，Credential Manager 读取失败返回
`safe_code=credential_store_unavailable`。任何
`verification_complete=False` 结果都必须携带非 `none` 的固定安全码。

只有 SDK 版本、固定参数、SSE/text/stop、message replay、取消、复用、密钥轮换、
本地请求上限、资源关闭、Target 清理和 logging 恢复全部为 True 时才返回 0。输出
不包含 API Key、assistant 正文、reasoning、continuation 或原始异常。

截至本轮只完成离线 Fake SDK 验证，尚未运行 `--confirm-real-api`，不能据此宣称
真实 HTTP、TLS、SSE、服务端行为或计费已经验证。
