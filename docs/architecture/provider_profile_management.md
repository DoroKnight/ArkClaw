# Provider Profile 元数据管理

## 边界

`ProviderProfileService` 是 CLI、未来 Qt 桌宠和 Gateway 管理 Provider Profile 的
统一应用服务。调用方不得直接修改 JSON。Repository 只接受以下非敏感领域类型：

- `ProviderProfile`
- `CredentialBinding`
- `ProfileId`
- `CredentialId`

`SecretValue`、API Key、Authorization 和 CredentialBlob 不属于 Repository API，
也不出现在 JSON schema。API Key 继续只由 `SecretStore`/Windows Credential
Manager 管理。删除 Profile 或 Binding 元数据不会删除 Credential Manager 中的
凭据。

## JSON schema version 1

配置文件由 Composition Root 指定路径。当前根文档为：

```json
{
  "schema_version": 1,
  "active_profile_id": "builtin-fake-default",
  "profiles": [
    {
      "schema_version": 1,
      "profile_id": "builtin-fake-default",
      "display_name": "Built-in Fake",
      "provider_id": "fake",
      "protocol": "internal",
      "base_url": null,
      "model": "fake",
      "credential_id": null,
      "capabilities": {
        "streaming": true,
        "tools": false,
        "embeddings": false,
        "continuation_mode": "replay_messages",
        "protocol": "internal"
      },
      "enabled": true
    }
  ],
  "credential_bindings": []
}
```

根对象和每类记录都采用精确字段集合；未知字段、重复 ProfileId、重复 CredentialId、
未知 Provider/协议、失效引用和非法领域值均视为损坏，不会被忽略。

OpenAI 和 DeepSeek Profile 从固定策略重建并逐字段比较：

- OpenAI：官方 HTTPS Origin + Responses；
- DeepSeek：官方 HTTPS Origin + Chat Completions；
- Fake：internal，无凭据；
- Ollama：只保留当前固定占位配置，不实现网络 Provider。

持久化 API 不接受 Base URL 参数。用户只能修改显示名称、模型、活动 Profile，以及
在同一 Provider 的 Binding 之间切换 CredentialId。协议、Origin、capabilities 和
Credential Provider 归属不能通过 JSON 或服务 API 改写。

## 原子写入与损坏处理

`JsonProviderProfileRepository` 每次变更执行：

1. 读取并完整验证旧文档；
2. 在目标文件同一目录创建临时文件；
3. 写入完整 UTF-8 JSON；
4. `flush()`；
5. `os.fsync()`；
6. `os.replace()` 原子替换。

临时写入、flush、fsync 或 replace 失败时会删除临时文件并保留旧文件。损坏 JSON
不会被静默重建；未知 `schema_version` 默认安全失败。只有显式注入
`ProviderProfileDocumentMigrator` 才能迁移旧版本，迁移结果仍必须通过当前 schema
与 Provider 策略校验。

公共异常只包含固定文本。底层 I/O、JSON、迁移、Factory 或 Provider 异常在离开
`except` 后映射，原始异常不会作为公共异常的 cause/context 暴露。

## CredentialBinding 引用

Binding 是非敏感授权元数据：

```text
CredentialId → ProviderId + fixed HTTPS Origin
```

规则：

- 云 Profile 保存前必须存在完全匹配的 Binding；
- CredentialId 不能改绑到另一个 Provider 或 Origin；
- 同一 Provider 可有多个 CredentialId 和多个 Profile；
- Profile 只能选择同一 Provider 的 CredentialId；
- 被任何 Profile 引用的 Binding 不能删除；
- 删除 Profile 不自动删除 Binding 或真实 Credential；
- 内置 Profile/Binding 使用稳定 ID，初始化是幂等操作，不重复生成记录；
- `OPENAI_MANUAL_TEST_CREDENTIAL_ID` 和
  `DEEPSEEK_MANUAL_TEST_CREDENTIAL_ID` 只属于人工验证脚本；生产 Policy、
  Repository 和 Service 均拒绝它们。生产 Target Resolver 同样固定拒绝；脚本所需
  映射由 `scripts/manual_credential_targets.py` 中的封闭 Resolver 显式注入；
- 人工验证测试 Target 不会由管理服务自动初始化为普通生产 Binding。

## 活动 Provider 切换

`ProviderProfileService.activate_profile()` 的顺序为：

```text
撤下旧 Provider
→ 上层明确选择 CANCEL_ACTIVE 或 WAIT_FOR_ACTIVE
→ TurnCoordinator 完成取消/等待
→ old_provider.aclose()
→ 使用最新 Binding 构造 ProviderFactory
→ 构造指定 Provider（无 fallback）
→ 持久化 active_profile_id
→ 发布新 Provider
```

Service 发布的是可撤销受管句柄，而不是允许绕过切换屏障的裸 Provider。切换开始时
先 revoke 旧句柄并将 `active_provider` 设为 `None`；即使调用方暂时缓存了旧句柄，
后续新请求也只会得到固定 `provider_switching` 失败，不能进入底层 Provider。
已经开始的 Turn 不会被句柄擅自终止，而是交给显式 Turn 策略处理。
旧 Provider 关闭失败、切换协调失败、新 Provider 构造失败或 active ID 持久化失败
都不会发布新 Provider。

Service 生命周期状态为 `inactive`、`active`、`switching`、
`cleanup_pending` 和 `closed`。旧 Provider 关闭失败或关闭期间被取消时，引用保留在
`retiring_providers`；候选 Provider 构造后若 active ID 持久化失败且候选关闭失败，
引用保留在 `candidate_cleanup_pending`。后续激活必须先同步重试全部 pending
清理，失败时不会调用 Factory；`aclose()` 也会重试全部保留资源。Service 不创建
后台清理 Task，`CancelledError` 原样传播。

上层必须显式提供 `ActiveTurnHandling.CANCEL_ACTIVE` 或
`ActiveTurnHandling.WAIT_FOR_ACTIVE`，并实现 `ActiveTurnCoordinator`。Service
不会自行猜测当前 Turn 应取消还是等待。

活动实例保存 `runtime_profile_id`、完整 Profile 快照和激活 options 快照。同步
`update_profile()` 对活动 Profile 只允许更新 `display_name`；model 或
CredentialId 必须先切换或停用。再次激活同一 ID 时，只有 Profile 与 options
快照完全相同才复用现有实例；外部 JSON 修改或 timeout、max_retries、stream
变化会固定失败，不会让持久化内容与运行时静默漂移。

Service 受管句柄在 COMPLETED 事件上为 continuation 附加 `profile_id`，不解析
opaque state。每次受管请求在创建 Delegate stream 前强制校验输入 continuation
的 `profile_id` 和 provider name；缺失或不匹配时返回
`provider_continuation_mismatch`，不会调用 Delegate。输出 continuation 只有在
`profile_id=None` 时才附加当前 ProfileId；Delegate 返回冲突 ProfileId 或错误
provider name 时安全失败并关闭底层流，不会通过静默重标掩盖错误归属。

Service 路径同时校验活动运行快照、`profile_id` 和 provider name。缺少
`profile_id` 的旧 continuation 只保留直接使用未受管 Provider 时的构造兼容性，
在受管运行时中安全拒绝。即使两个 Profile 使用同一 Provider，旧 Profile 的
continuation 也不能在新 Profile 激活时复用。

候选 Provider 发布前还会核对 `delegate.name == profile.provider_id.value`，以及
Delegate capabilities 的 protocol 与 Profile protocol 完全一致。错误 Factory
返回的候选不会发布；候选关闭失败时继续由 `candidate_cleanup_pending` 保存并
重试。

## 兼容层

本阶段没有删除或改变：

- `RuntimeConfig`
- `ProviderName`
- `ProviderFactory.create()`
- 旧 SecretStore 方法和固定 Credential Target
- 当前 CLI
- 两个人工验证入口

新入口通过 ProviderProfileService 调用 `ProviderFactory.create_profile()`。旧 CLI
仍可继续使用 `ProviderFactory.create(RuntimeConfig)`；未来 Qt 和 Gateway 应只依赖
Service，不得直接依赖 JSON Adapter。

本阶段所有验证均为 Fake Store、Fake SDK 和临时目录测试，没有自动测试连接、真实
Credential Manager 或真实 API 请求。
