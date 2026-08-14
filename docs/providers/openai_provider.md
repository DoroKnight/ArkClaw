# OpenAI Provider

## 边界

`OpenAIProvider` 实现领域层的 `LLMProvider`，但 OpenAI SDK 只出现在
`infrastructure/llm/`。`AgentLoop`、`domain`、`application` 和 `config` 不识别
任何 SDK 事件或异常类型。

生产适配分为两层：

1. `openai_sdk.py` 包装官方 `AsyncOpenAI`，把 SDK 对象转换为窄的类型化事件；
2. `openai_provider.py` 实现请求映射、流状态机、工具聚合、凭据轮换和
   continuation。

单元测试注入类型化 Fake SDK，不构造复杂 SDK 对象图，也不发起网络请求。

## 请求与隐私

每个 Responses API 请求显式发送：

- `store=False`；
- `RuntimeConfig.openai_model` 对应 `model`；
- `LLMRequest.instructions` 对应 `instructions`；
- `LLMRequest.messages` 对应 `input`；
- `LLMRequest.max_output_tokens` 对应 `max_output_tokens`；
- `RuntimeConfig.provider_timeout_seconds` 和 `openai_max_retries` 在 Client 创建时
  配置。

函数工具映射为 Responses API function tools。记忆内容始终作为带来源和
`untrusted_memory_data` 边界的 user 数据发送，不会拼入 developer/system
instructions。

## 流状态机

文本 `response.output_text.delta` 转换为 `LLMEvent.text_delta()`；空 delta 被忽略。
函数参数在 `response.function_call_arguments.delta` 中聚合，并只在
`response.function_call_arguments.done` 这个规范化完成点解析和发出一次
`LLMEvent.call_tool()`。参数必须是 JSON object。

`response.completed` 只暂存终止状态；Provider 会继续验证直到 EOF，因而能拒绝
重复终止或终止后的业务事件。缺少终止事件、空响应、未完成工具、未知错误终止状态
和非法结构都映射为固定的 `invalid_response` 或安全 Provider 错误。

## continuation 与 `store=False`

官方 Conversation state 文档要求客户端手动管理无状态历史时重放完整响应
`output`，包括 reasoning items；文档的 `previous_response_id` 示例使用服务端响应
链，而 `store=false` 会关闭响应对象的默认保存：

- [Conversation state](https://developers.openai.com/api/docs/guides/conversation-state)
- [Streaming Responses](https://developers.openai.com/api/docs/guides/streaming-responses)
- [Function calling](https://developers.openai.com/api/docs/guides/function-calling)

因此本实现不把 `previous_response_id` 作为 `store=False` 下的唯一 continuation。
版本 `2` continuation 使用确定性 UTF-8 JSON，保存下一轮所需的本地会话输入历史、
受控类型的响应输出项、已消费消息指纹和上一条 assistant 文本指纹。每个
`OpenAIProvider` 实例生成独立的随机 HMAC-SHA256 密钥，对 canonical JSON payload
签名；签名密钥不来自 API Key，凭据轮换不会改变它，新 Provider 实例不能重放旧
实例的 continuation。它只通过
`ProviderContinuation.state` 在内存中传递，`repr` 不显示内容，也不写入配置、
SQLite 或日志；`aclose()` 会释放 Provider 持有的签名密钥引用。

恢复时先验证严格 envelope 和 HMAC，再解释 payload。错误 Provider、版本 `1`、
非法 UTF-8/JSON、重复字段、签名缺失或篡改、未知/高权限历史项、消息前缀不匹配
和超过 1 MiB 的状态都会被拒绝。失败、取消或不完整响应不会生成新 continuation。

工具参数使用严格 JSON object 解析：拒绝 `NaN`/无穷值、重复 key、顶层数组或
标量、非有限浮点数、超过 32 层的结构和超过 1 MiB 的参数。流式 delta 按 UTF-8
字节累计，越界时在 `done` 前立即 fail closed。

## 资源生命周期

Provider 每次请求前重新读取 `SecretStore` 并比较非持久化 SHA-256 凭据指纹：

- 缺少密钥时返回 `missing_api_key`，不创建 SDK 请求；
- 删除密钥会关闭缓存 Client 和活动流；
- 更换密钥会关闭旧 Client/流，再创建新 Client；
- 取消一个流只关闭当前响应流，Provider 可继续复用；
- `aclose()` 幂等关闭所有活动流和 SDK Client。

生产 SDK 包装器只在底层 `close()` 成功后标记资源已关闭。底层关闭失败会转换为
不保留原始异常链的 `resource_close_failed`，失败资源进入 Provider 的待清理
注册表；下一次请求会先重试清理，清理仍失败时不发送新请求。重复调用
`aclose()` 也会重试待清理资源。一次请求的 Stream 关闭失败会使该请求返回安全
失败，不能以完成事件误报成功。

Provider 使用独立 lifecycle lock 串行化请求初始化、凭据轮换、pending 重试、
Stream 退休和 `aclose()`。普通状态锁只用于短时移动引用，不在其中执行 SDK
`create()` 或 `close()`。资源状态明确分为 active、pending 和 closing；关闭期间
资源保留在 closing 注册表中，不会因临时清空集合而表现为不存在。

凭据轮换先隔离旧 Client/Stream，再完成全部旧资源关闭；只有关闭全部成功后才创建
和发布新 Client。并发请求在 lifecycle lock 等待结果：关闭失败时全部返回安全
`provider_unavailable`，不会提前调用新 Client。`asyncio.CancelledError` 始终继续
传播；取消时未确认关闭的资源仍留在 pending/closing，后续显式 `aclose()` 或请求
可以继续清理，不创建后台清理 Task。

SDK 请求超时由 OpenAI Client 处理，Agent 总回合超时仍由 `AgentLoop` 独立处理。
实现不宣称能够可靠擦除 Python 字符串或不可变 bytes。

## 自动验证

默认测试只使用明显为假的凭据和 Fake SDK：

```powershell
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider
```

该命令不会访问 OpenAI API，也不会运行默认跳过的 Windows Credential Manager
原生集成测试。

## 显式人工 OpenAI 验证

`scripts/manual_openai_verification.py` 是唯一的真实 API 验证入口，默认执行只会
报告未启用，不访问 Credential Manager 或网络。它固定使用测试 Target
`ArkClaw/Test/OpenAI/APIKey`、`gpt-5-mini`、`store=False`、25,000 个
`max_output_tokens`、60 秒单请求 SDK timeout、600 秒人工验证协作式整体
timeout、零 SDK 重试和最多 7 次 `responses.create()` 调用预算。第 8 次调用会
在进入真实 Client 前由本地
Audit 边界拒绝，且不计入真实调用数。API Key 只通过隐藏输入读取，不接受命令行
参数或环境变量；输出预算和超时也不是 CLI 参数。

`gpt-5-mini` 是推理模型。Responses API 的 `max_output_tokens` 同时限制可见输出
和 reasoning tokens；官方推理指南还说明，额度可能在生成任何可见文本前耗尽，
并建议在开始验证推理模型时至少预留 25,000 token。因此原来的 16 token 无法可靠
区分“预算先被隐藏推理耗尽”和“流协议/Provider 不兼容”。本入口采用固定 25,000
作为兼容性验证上限，不自动提高、不重试。该上限只是请求参数，不代表每次都会实际
消费 25,000 token，也不是最终费用承诺；用户在每次真实运行前仍须查看当前官方
价格并明确接受最多 7 次请求的成本风险。

- [Reasoning models](https://developers.openai.com/api/docs/guides/reasoning)
- [GPT-5 mini model](https://developers.openai.com/api/docs/models/gpt-5-mini)

当前固定 SDK `2.48.0` 的类型定义允许 `reasoning.effort`，但官方
`gpt-5-mini` 模型页没有列出该模型支持的具体 effort 值。为避免猜测，本入口和
普通生产请求均不显式发送 `reasoning` 字段，继续使用服务端对该模型的默认行为。

脚本对固定 Target 实施本次运行所有权：

1. 精确确认 `RUN` 后才构造 Credential Store；
2. 在调用 `getpass` 前只读检查 Target；已占用时返回
   `safe_code=test_target_occupied`，不读取密钥输入、不删除、不覆盖、不创建 Client；
3. 隐藏输入结束后、真正写入前再次检查 Target，以缩小并发占用窗口；
4. 人工验证专用 `OwnedTestSecretStore` 包装固定 Target；只有本次写入和读取复核
   成功后才取得清理所有权；
5. Provider 只持有该包装层。包装层在 Provider 每一次读取及每次覆盖、恢复、删除
   前，从底层 Store 重读并用内存 SHA-256 指纹做常量时间所有权比较；
6. 所有权丢失时报告 `safe_code=test_target_ownership_lost`，不再覆盖、删除或发送
   请求，并关闭已创建资源；
7. `finally` 也只在值级所有权复核通过后删除，并再次读取确认 Target 已不存在；
8. 写入失败或从未取得所有权时绝不执行删除。

这些检查不是 Credential Manager 的原子 compare-and-swap（CAS），只能缩小
time-of-check/time-of-use（TOCTOU）窗口，不能从数学上消除检查与写入/删除之间的
最后竞争。但如果替换发生在 Provider 读取前，包装层只计算外部值的临时指纹，
立即标记 ownership lost 并抛出固定安全错误，绝不把该 `SecretValue` 返回给
Provider。入口继续使用固定测试 Target，不触碰生产 Target
`ArkClaw/OpenAI/APIKey`。

脚本不会读取并暂存旧凭据后再恢复。若 Target 已占用，需要独立处理：在 Windows
“凭据管理器”界面中单独确认固定名称 `ArkClaw/Test/OpenAI/APIKey` 确实是可丢弃
的测试凭据，再由用户明确删除；该清理不隐含在真实 API 验证流程中，也不需要网络。

人工确认成本并确认测试 Target 当前为空后，在 Windows PowerShell 中运行：

```powershell
.\.venv\Scripts\python.exe .\scripts\manual_openai_verification.py --confirm-real-api
```

脚本使用 `ManualVerificationChecks` 汇总所有安全判定。SSE 检查要求
`response.created` 和 `response.completed` 各恰好一次、至少一个非空
`response.output_text.delta`，严格满足 created < first delta < completed，并拒绝
错误终止、重复终止及 completed 后事件。continuation 检查在内存中逐项比较第二轮
SDK input，要求第一轮全部 output items（包括 reasoning、encrypted reasoning、
message 和 function_call）保持顺序且各出现一次，随后才是新 user 消息；手工加入
的 assistant 消息不得重复响应 output message。

当真实 Responses API 以 `status=incomplete` 且
`incomplete_details.reason=max_output_tokens` 结束时，无论发生在首个 delta 前，
还是已经出现部分 delta，验证都返回非零并报告固定
`safe_code=verification_output_budget_exhausted`。该结果表示验证不确定，不会被
误报为 `invalid_response`、SSE 时序错误、continuation 不兼容或 Provider 实现
失败；脚本不输出部分正文、reasoning 或 continuation，也不会自动重试、提高预算
或发送额外请求。用户必须重新检查价格并再次明确接受成本后，才能重新运行。
单请求 SDK timeout 固定为 60 秒并映射为
`safe_code=verification_request_timeout`。人工验证协作式整体 timeout 固定为
600 秒：到时由 `asyncio.wait_for()` 向内部 Task 发出取消，但会继续等待取消传播
和 `finally` 清理完成，之后才以
`safe_code=verification_runtime_timeout` 返回。因此实际总运行时间可能超过
600 秒；该安全码只表示已经触发协作式取消，不表示进程在 600 秒内退出。

当前没有实现进程级硬截止。asyncio 取消依赖协程到达可取消点，
`wait_for()` 也会等待取消真正完成；同步阻塞代码不能被事件循环 timeout 抢占。
如果 SDK、资源关闭或同步 Windows Credential Manager 调用持续阻塞，用户可能
仍需人工终止进程。强制终止可能使测试 Target 或底层资源来不及清理，之后必须
人工检查固定测试 Target 和相关资源状态。若产品必须保证进程级硬截止，应单独
设计并复审父子进程 watchdog，本入口当前不实现该机制。

首个 delta 后取消、创建期取消、Provider 复用、无效凭据映射、轮换后的旧 Client
关闭、恢复密钥、删除密钥后的零新增请求、`store=False`、请求预算、所有
Stream/Client 关闭、从未发生关闭失败、Target 所有权与清理也必须全部为真才返回
0。即使某次关闭失败后重试成功，本次人工验证仍返回非零。

无参数入口是预期的安全惰性状态，输出
`safe_code=manual_verification_disabled` 并返回退出码 0。带
`--confirm-real-api` 但确认失败，或验证开始后的任一检查、超时、资源关闭及 Target
清理失败，统一返回退出码 2；只有全部验证成功返回 0。该规则与 DeepSeek 人工入口
一致。

全局 `logging.disable` 状态会在成功、失败和异常路径中恢复。输出只包含安全状态与
计数，不显示密钥、assistant 正文、请求/响应正文、工具参数、continuation 或原始
异常。它不会使用生产 Target，也不会在 pytest 中自动运行。

这里的 7 次预算约束的是本地 `responses.create()` 调用次数，而不是服务端计费的
绝对证明。创建期取消只能证明本地任务收到取消、没有注册活动 Stream；请求是否
已到达服务端以及底层 TCP/TLS 清理由 SDK/httpx 管理。

验证结论分三层：人工脚本的 Audit 只能证明 Provider 边界实际提交的请求对象；
离线 Adapter 单元测试用 Fake `AsyncOpenAI` 证明官方包装器调用
`responses.create()` 时显式传递 `store=False`、`stream=True`，不传
`previous_response_id`，并在构造 Client 时传递 `max_retries=0`。只有真实
HTTP/wire 抓包才能证明最终线上报文与服务端接收事实；当前阶段未进行网络访问，
因此不声称已验证 HTTP、SSE、TLS、计费或 wire 层，本轮也未执行真实 API 验证。
