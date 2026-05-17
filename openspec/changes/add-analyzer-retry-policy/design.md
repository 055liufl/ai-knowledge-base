## Context

当前 `pipeline/model_client.py` 实现了 `chat_with_retry()` 函数，为 OpenAI 兼容 API（DeepSeek / Qwen / OpenAI）提供基础重试能力。该函数被 `quick_chat()` 调用，而 `quick_chat()` 又在 `pipeline.py` 的 `analyze_item()` 中被使用。

现有实现存在以下问题：
1. **参数过于宽松**：`timeout=60s`, `max_retries=3`, `base_delay=1.0s`，导致单条数据最坏情况可阻塞 4 分钟以上
2. **错误分类粗糙**：未区分 `ConnectTimeout`（连接失败）与 `ReadTimeout`（服务器已接收但响应超时），后者重试容易导致重复计费
3. **退避策略无差异化**：三家 provider 的 rate limit 策略不同，但使用相同的退避参数
4. **未感知 429 响应头**：遇到 rate limit 时不读取 `Retry-After`，可能退避不足或过度

约束条件：
- 不引入新依赖（保持 `httpx` 单依赖）
- 不改 `pipeline.py` 的调用方式（向后兼容）
- 不做业务层重试（JSON 解析失败不在 model_client 处理）

## Goals / Non-Goals

**Goals:**
- 将单条数据最坏等待时间从 ~4 分钟降至 ~1.6 分钟
- 精确分类可重试错误，降低重复计费风险
- 支持按 Provider 配置差异化退避策略
- 支持读取 HTTP 429 的 `Retry-After` 响应头
- 保持 `pipeline.py` 零改动

**Non-Goals:**
- Provider 级 fallback（一个 provider 挂了切另一个）
- Circuit breaker
- Async / 并发改造
- 业务层重试（如 JSON 解析失败后的 prompt 调整重试）
- Pipeline 断点续传 / 增量保存

## Decisions

### Decision 1: 参数默认值保守化

**选择：** `timeout=30.0`, `max_retries=2`, `base_delay=2.0`

**理由：**
- 批量分析场景下，单条 prompt 长度通常不超过 2000 字符（约 500 tokens），30 秒足够完成
- `max_retries=2`（初始请求 + 2 次重试 = 最多 3 次）在"快速失败"和"容忍瞬时故障"之间取得平衡
- `base_delay=2.0` 给 rate limit 更长的冷却时间，降低连续触发 429 的概率

**替代方案考虑：**
- 保持 `max_retries=3`：拒绝，因为批量场景下最坏时间不可接受
- `timeout=45s`：考虑过，但 30s 已覆盖绝大多数情况，且能更快暴露真正的性能问题
- 通过环境变量动态调整：过度设计，当前场景不需要

### Decision 2: `ReadTimeout` 单独限制重试次数

**选择：** `ReadTimeout` 最多重试 1 次，其他可重试错误最多 2 次

**理由：**
- `ReadTimeout` 的特殊性在于：请求可能已经到达服务器并正在处理（或已完成处理，响应在传输中丢失）
- 这种情况下重试会导致同一条 prompt 被处理两次，产生重复计费
- 限制为 1 次是在"容错"和"成本控制"之间的折中

**替代方案考虑：**
- 完全不重试 `ReadTimeout`：过于严格，网络抖动时失败率会显著上升
- 对 `ReadTimeout` 使用更长的退避（如 5s）：无法降低重复计费概率，只是推迟了重试时间

### Decision 3: Provider 差异化配置通过 `_PROVIDER_CONFIG` 扩展

**选择：** 在现有 `_PROVIDER_CONFIG` 字典中增加 `retry_policy` 子字典，而非新建配置系统

**理由：**
- 最小化改动范围，利用现有配置结构
- `OpenAICompatibleProvider.__init__` 可以直接读取并保存，无需额外的配置加载逻辑
- 新 provider 只需在配置中加一行 `retry_policy`，无代码改动

**替代方案考虑：**
- 新建 `RetryConfig` dataclass：增加代码量，且当前场景不需要复杂的配置组合
- 环境变量覆盖：`LLM_MAX_RETRIES` 等，但无法支持 per-provider 差异化

### Decision 4: 429 `Retry-After` 优先于指数退避

**选择：** 遇到 429 时，先检查响应头 `Retry-After`，有则用，无则回退到指数退避

**理由：**
- Provider 最清楚自己什么时候能恢复服务，`Retry-After` 是最准确的等待时间
- DeepSeek 和 OpenAI 都会在 429 响应中携带此头
- 实现简单：`exc.response.headers.get("retry-after")`，无额外依赖

**替代方案考虑：**
- 总是使用指数退避，忽略 `Retry-After`：简单但可能退避不足或过度
- 取 `max(Retry-After, calculated_backoff)`：过度保守，通常 `Retry-After` 已经考虑了服务器负载

### Decision 5: 不在 `pipeline.py` 引入业务层重试

**选择：** `analyze_item()` 保持现状，JSON 解析失败返回 `None`，不重试

**理由：**
- 业务层重试需要修改 prompt（如附加"只输出 JSON"的约束），这改变了 LLM 的输入，可能导致输出质量变化
- 当前 JSON 解析失败率较低，投入产出比不高
- 保持 scope 清晰：model_client 只管 HTTP 层，pipeline 只管业务流程

**替代方案考虑：**
- 在 `analyze_item()` 内对 `JSONDecodeError` 重试 1 次：技术上可行，但属于后续迭代范围

## Risks / Trade-offs

| 风险 | 影响 | 缓解 |
|---|---|---|
| `timeout` 从 60s 降到 30s，某些复杂分析（长文本 + 高 max_tokens）可能超时 | 低 | 调用方可通过显式传参覆盖；批量场景下 prompt 长度可控 |
| `ReadTimeout` 只重试 1 次，网络波动时整体失败率上升 | 中 | 失败时记录明确日志（含 provider、status code、耗时），方便用户手动重跑单条 |
| Provider 配置中遗漏 `retry_policy` 导致使用不合适的默认值 | 低 | 代码中设置合理的全局默认值（`base_delay=2.0, max_retries=2`），缺失时自动回退 |
| 429 的 `Retry-After` 值过大（如 60s）导致单条阻塞过久 | 低 | `Retry-After` 是 provider 的建议值，通常合理；未来可考虑设置上限（如 max 30s）作为保险 |

## Open Questions

1. 是否需要为 `Retry-After` 设置上限（如最多等 30s）？目前按 provider 建议值等待，但极端情况下可能过长。
2. 是否需要暴露环境变量覆盖全局默认值（如 `LLM_TIMEOUT`, `LLM_MAX_RETRIES`）？当前认为不需要，但用户反馈可能改变这个判断。
