## Context

当前 `pipeline/model_client.py` 的 `chat()` 方法无重试逻辑，`pipeline.py::analyze_item()` 调用它时，一旦遇到 timeout 或 rate limit，整个脚本退出，已消耗的 tokens 沉没。

历史事故：50 条数据跑到第 23 条 timeout，前 22 条 ¥0.04 成本浪费，当天知识库空。

## Goals / Non-Goals

**Goals:**
- 在 `chat()` 上套一层指数退避重试，扛住 timeout / rate limit / 5xx / connection reset
- 区分"可重试"与"不可重试"异常，不浪费 tokens 在内容层错误上
- 成本追踪：记录每次 API 调用（含失败重试）的 token 消耗
- 终极失败 graceful degradation：降级 summary，标记 `status="degraded"`，pipeline 继续跑完其他 items

**Non-Goals:**
- Provider 级 fallback（OpenAI 挂了切 DeepSeek）
- Circuit breaker
- Async / 并发重试
- 读取 `Retry-After` header（统一走 exp backoff）
- 修改 step_collect / step_organize / step_save

## Decisions

### Decision 1: 用装饰器而非内联重构

**选择：** 新增 `with_retry` 装饰器，套在 `chat()` 上。

**理由：**
- 装饰器与业务逻辑解耦，`chat()` 本身不需要知道重试存在
- 未来可以给其他方法（如 `stream()`）复用
- 比内联修改 `chat()` 更干净

**替代方案：** 直接改 `chat()` 内部加 try/except 循环 ——  rejected，会污染原始逻辑。

### Decision 2: 可重试异常白名单

**选择：** 只重试以下异常：
- `httpx.TimeoutException`（含 `APITimeoutError`）
- `httpx.ConnectError`（含 `APIConnectionError`）
- `RateLimitError`
- `APIStatusError where status_code >= 500`

**理由：**
- 这些是"provider 侧瞬时故障"，重试有意义
- `json.JSONDecodeError`、`KeyError`、`ValueError` 是内容/解析层错误，重试不会变好

### Decision 3: 重试策略参数

**选择：** `max_attempts=3, base_delay=1s, max_delay=20s, jitter=1.0-1.5× 只加不减`

**理由：**
- 3 次尝试（初始 + 2 次重试）在"容错"和"不卡死"之间平衡
- 1s→2s→4s 的退避足够应对大多数 rate limit
- max_delay=20s 封顶，防止极端情况无限等待
- jitter 只加不减：避免所有并发请求同时重试导致雪崩

### Decision 4: 成本追踪

**选择：** 每次 API 调用（包括失败的重试）都记录一次 cost_tracker 条目。

**理由：**
- 失败的调用 tokens=0（因为没拿到 response），但需要记录"发生了多少次失败尝试"
- 成功的调用按 `response.usage` 记录实际 tokens
- 方便后续分析"重试成本占比"

### Decision 5: Graceful Degradation

**选择：** 终极失败时，用原始 `raw_content` 的前 200 字作为降级 summary，`status` 标记为 `"degraded"`。

**理由：**
- 不因为单条失败中断整个 pipeline
- 降级后的内容仍有价值（比完全丢失好）
- `status="degraded"` 方便后续人工 review

**⚠️ 注意：** proposal 声明"不改 step_collect / step_organize / step_save"，但标记 `status="degraded"` 需要修改 `pipeline.py` 的 `standardize()` 函数。这是一个 scope 矛盾，实现时需要在 `standardize()` 里加一行 `status = "degraded" if analysis_failed else entry.get("status", "pending")`。

## Risks / Trade-offs

| 风险 | 影响 | 缓解 |
|---|---|---|
| `max_attempts=3` 在严重故障时仍会连续失败 3 次，累积延迟 | 中 | 单条最坏 1+2+4+20=27s，可控 |
| 不吃 `Retry-After`，对严格 rate limit 的 provider（如 OpenAI）可能退避不足 | 低 | 目前主要用 DeepSeek，rate limit 较松；未来迭代再加 |
| Graceful degradation 的降级 summary 质量差 | 低 | 标记 `degraded` 后人工可识别并补录 |
| `status="degraded"` 需要改 `pipeline.py`，与"不改 step_xxx"声明冲突 | 中 | 实际改动仅 1 行，在 `standardize()` 里判断即可 |

## Open Questions

1. `cost_tracker` 的输出格式：是写日志、写文件、还是返回给调用方？建议先简单打印日志，未来持久化。
2. `with_retry` 装饰器是否也套在 `quick_chat()` 上？是的，因为 `quick_chat()` 内部调 `chat()`，装饰器会生效。
