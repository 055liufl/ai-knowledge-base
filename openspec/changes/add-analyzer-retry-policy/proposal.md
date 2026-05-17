## Why

当前 `pipeline/model_client.py` 已提供基础重试能力 `chat_with_retry`，但在实际批量分析场景中（50 条数据顺序执行）暴露出三个问题：单条卡住时间过长（最坏情况超 4 分钟）、错误分类不精确（`ReadTimeout` 重试导致重复计费）、退避策略一刀切（三家 provider 的 rate limit 策略不同）。本次调优让 LLM 调用层的重试更保守、快速、可控，降低批量分析的整体时间风险。

## What Changes

- **重试参数调优**：`timeout` 60s→30s，`max_retries` 3→2，`base_delay` 1.0s→2.0s，将单条最坏情况从 ~4 分钟降到 ~1.6 分钟
- **错误分类白名单制**：明确只重试 `ConnectTimeout`/`ConnectError`、HTTP 429/502/503/504；`ReadTimeout` 最多重试 1 次（降低重复计费风险）；客户端错误（400/401/403/404/422）直接失败
- **Provider 差异化退避策略**：在 `_PROVIDER_CONFIG` 中增加 `retry_policy` 字段，DeepSeek/OpenAI/Qwen 分别使用不同的 `base_delay`（1.5s / 3.0s / 2.0s）
- **429 响应头感知**：优先读取 `Retry-After` 响应头，而非固定指数退避
- **`pipeline/pipeline.py` 无改动**：`analyze_item` 继续调用 `quick_chat`，不引入业务层重试

## Capabilities

### New Capabilities

- `llm-retry-policy`: LLM 调用层的重试策略配置，包括参数默认值、可重试错误分类、Provider 差异化退避、429 响应头感知

### Modified Capabilities

- 无现有 spec 需要修改（`openspec/specs/` 为空）

## Impact

- **代码文件**：`pipeline/model_client.py`（重试逻辑、Provider 配置、常量默认值）
- **接口变化**：`chat_with_retry()` 参数默认值变化（向后兼容，不影响显式传参的调用方）
- **依赖变化**：无新增依赖
- **行为变化**：默认重试次数减少、超时缩短，失败更快；退避策略因 provider 而异
