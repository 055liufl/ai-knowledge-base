# Proposal: Pipeline LLM Retry 机制调优

## 背景

当前 `pipeline/model_client.py` 已提供 `chat_with_retry` 函数，为 LLM 调用提供基础重试能力。但在实际批量分析场景中（50 条数据顺序执行），暴露出以下问题：

1. **单条卡住时间过长**：默认 `timeout=60s` + `max_retries=3`，单条最坏情况可超过 4 分钟，导致整体进度不可预期
2. **错误分类不精确**：未区分 `ConnectTimeout` 与 `ReadTimeout`，后者重试容易导致重复计费
3. **退避策略一刀切**：DeepSeek、Qwen、OpenAI 的 rate limit 策略不同，固定退避参数不是最优
4. **前序 tokens 浪费**：Pipeline 跑到中途因单条卡死或持续失败而中断，已成功的分析结果未保存

## 目标

让 LLM 调用层的重试机制更**保守、快速、可控**，降低批量分析的整体时间风险，减少不必要的 token 浪费。

## 范围

### In Scope

- `pipeline/model_client.py`：
  - 重试参数调优（timeout、max_retries、base_delay）
  - 可重试错误的精确分类（白名单制）
  - 按 Provider 差异化的退避策略配置
  - `ReadTimeout` 与 `ConnectTimeout` 区分处理
- `pipeline/pipeline.py`：
  - 保持现有 `analyze_item` 调用方式不变
  - 不新增业务层重试

### Out of Scope

- Provider 级 fallback（OpenAI 挂了切 DeepSeek）
- Circuit breaker
- Async / 并发改造
- 业务层重试（JSON 解析失败、字段缺失等）
- Pipeline 断点续传 / 增量保存

## 设计决策

### 决策 1：参数调优——保守重试，快速失败

| 参数 | 当前值 | 建议值 | 理由 |
|---|---|---|---|
| `timeout` | 60.0 | 30.0 | 批量分析够用了，降低重复计费风险 |
| `max_retries` | 3 | 2 | 减少最坏情况等待时间 |
| `base_delay` | 1.0 | 2.0 | 初期间隔拉长，给 rate limit 喘息时间 |

最坏情况时间：
- 修改前：`60 × 4 + (1 + 2 + 4) = 247s`（约 4 分钟/条）
- 修改后：`30 × 3 + (2 + 4) = 96s`（约 1.6 分钟/条）

### 决策 2：错误分类白名单制

明确只重试以下错误，其余直接失败：

```python
_RETRYABLE_EXCEPTIONS = {
    httpx.ConnectTimeout,      # 连不上，可以重试
    httpx.ConnectError,        # 连接失败，可以重试
}
_RETRYABLE_STATUS_CODES = {429, 502, 503, 504}
_READ_TIMEOUT_MAX_RETRIES = 1  # ReadTimeout 最多重试 1 次
```

不重试：
- `400, 401, 403, 404, 422` 等客户端错误
- `ValueError`（配置错误）
- `json.JSONDecodeError`（业务层错误，不在 model_client 处理）

### 决策 3：Provider 差异化退避策略

在 `_PROVIDER_CONFIG` 中增加 `retry_policy` 字段：

```python
"deepseek": {
    # ... existing config ...
    "retry_policy": {
        "base_delay": 1.5,
        "max_retries": 2,
    }
},
"openai": {
    # ... existing config ...
    "retry_policy": {
        "base_delay": 3.0,
        "max_retries": 2,
    }
},
"qwen": {
    # ... existing config ...
    "retry_policy": {
        "base_delay": 2.0,
        "max_retries": 2,
    }
}
```

`chat_with_retry` 读取 provider 配置中的 `retry_policy`，没有则回退到全局默认值。

### 决策 4：429 响应头感知

如果 HTTP 429 响应包含 `Retry-After` 头，优先使用该值，而非指数退避计算。

## 具体改动

### 文件 1：`pipeline/model_client.py`

1. 修改全局默认常量
2. 在 `_PROVIDER_CONFIG` 各 provider 下增加 `retry_policy`
3. 重构 `chat_with_retry` 的错误分类逻辑
4. 增加 `Retry-After` 头读取
5. `OpenAICompatibleProvider.__init__` 读取并保存 `retry_policy`

### 文件 2：`pipeline/pipeline.py`

无改动。`analyze_item` 继续调用 `quick_chat`，不引入业务层重试。

## 验收标准

- [ ] `chat_with_retry` 的默认 `max_retries` 为 2，`timeout` 为 30s
- [ ] `ReadTimeout` 最多只重试 1 次
- [ ] `401, 403, 400` 等客户端错误不触发重试，直接抛异常
- [ ] DeepSeek/OpenAI/Qwen 的退避基数不同（1.5s / 3.0s / 2.0s）
- [ ] 429 响应带 `Retry-After` 头时，按该值等待
- [ ] `pipeline.py` 无需修改即可正常工作
- [ ] 本地 dry-run 通过（`python pipeline/pipeline.py --dry-run --limit 5`）

## 风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| timeout 从 60s 降到 30s，某些复杂分析可能超时 | 低 | 观察实际运行情况，必要时通过环境变量覆盖 |
| ReadTimeout 只重试 1 次，网络波动时失败率上升 | 中 | 失败时记录明确日志，用户可手动重跑单条 |
| Provider 配置变化后，未来加新 provider 容易遗漏 retry_policy | 低 | 代码中设置合理默认值，缺失时自动回退 |

## 相关代码

- `pipeline/model_client.py` — `chat_with_retry()`（第 367-451 行）
- `pipeline/model_client.py` — `_PROVIDER_CONFIG`（第 33-63 行）
- `pipeline/pipeline.py` — `analyze_item()`（第 412-482 行）

## 后续可能扩展（不在本次范围）

1. **业务层重试**：对 `JSONDecodeError` 重试 1 次，附加更严格的 system prompt
2. **Provider fallback**：OpenAI 挂了自动切 DeepSeek
3. **增量保存**：每分析完一条立即落盘，支持断点续传
4. **并发分析**：asyncio / 线程池并发调用 LLM
