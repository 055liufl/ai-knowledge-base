## Context

当前 pipeline 的 LLM 调用链路：

```
pipeline.py:analyze_item()
    └── quick_chat() [model_client.py]
        └── chat_with_retry() [model_client.py]
            └── OpenAICompatibleProvider.chat() [model_client.py]
                └── httpx.Client.post() → DeepSeek/Qwen/OpenAI API
```

`chat_with_retry()` 已实现网络层重试（timeout、connect error、5xx、429），但未覆盖 LLM 返回 200 但内容格式异常的场景。`analyze_item()` 对 JSON 解析失败仅返回 None，不会触发重试，导致已消耗的 tokens 浪费。

## Goals / Non-Goals

**Goals:**
- 网络错误和内容格式错误均触发重试，单条成功率提升至 99%+
- 重试过程可观测（重试次数、失败原因记录）
- 支持断点续跑，避免中断后重复分析已消费 tokens 的数据
- 对现有 step_collect / step_organize / step_save 零侵入

**Non-Goals:**
- Provider 级 fallback（OpenAI 挂了切 DeepSeek）
- Circuit breaker
- Async / 并发优化
- 修改数据采集或保存逻辑

## Decisions

### 1. 内容错误重试放在 model_client 层而非 pipeline 层
**选择**: 扩展 `chat_with_retry()` 增加一个可选的 `validator` 回调参数，由调用方传入内容校验函数。
**理由**: 
- 保持重试逻辑集中，避免 pipeline 和 model_client 都有重试逻辑造成混乱
- `analyze_item()` 只需传入 JSON schema 校验器，无需关心重试实现
- 其他调用方（如有）也可复用

**替代方案**: 在 `analyze_item()` 里自己写 while 循环重试。 rejected，因为会分散重试逻辑，且无法复用指数退避。

### 2. 校验失败使用与网络错误相同的退避策略
**选择**: JSON 解析失败也走指数退避 + jitter，最大重试次数独立计算但与网络错误共享同一计数器。
**理由**: 
- 内容错误通常是模型临时"抽风"，稍作等待后重试大概率成功
- 统一策略降低复杂度

### 3. 断点续跑基于文件系统而非内存状态
**选择**: `run_pipeline()` 在分析前检查 `knowledge/articles/` 中是否已存在同 URL 的文章，若存在则跳过。
**理由**:
- 无需引入数据库或外部存储，最简单可依赖
- `save_article()` 的文件名包含 source_platform + date + slug，URL 信息已存入文件内容
- 缺点：需要读取已存在的文件做 URL 比对，有一定 I/O 开销，但可接受

**替代方案**: 在 raw data 中标记 analyzed。rejected，因为会修改采集数据的格式。

### 4. 不重试 4xx 客户端错误（除 429 外）
**选择**: 保持现有行为，401/403/400 直接失败。
**理由**: 客户端错误通常是配置问题（API key 错误、参数非法），重试不会成功。

### 5. 记录重试次数但不设 token 预算上限
**选择**: `Usage` 增加 `retry_count` 字段用于统计，不限制额外 token 消耗。
**理由**: 默认 max_retries=3，额外成本可控；设预算可能导致"差一次就成功但被迫放弃"的浪费场景。

## Risks / Trade-offs

- **[Risk] 内容错误重试增加 token 消耗** → **Mitigation**: 内容错误重试次数上限与网络错误共享（默认 3 次），且内容错误发生率较低（<5%）
- **[Risk] 断点续跑误跳过** → **Mitigation**: 严格按 URL 匹配，URL 是数据的唯一标识；支持 `--force` 参数覆盖（未来扩展）
- **[Risk] Retry-After 值过大导致 pipeline 卡住** → **Mitigation**: 对 Retry-After 设置上限（如最多等 60 秒），超过则回退到指数退避

## Migration Plan

无需迁移。本改动完全向后兼容：
- `chat_with_retry()` 新增 `validator` 参数为可选，现有调用不受影响
- `Usage` 新增字段有默认值，不影响已有逻辑
- 断点续跑为新增行为，不改变现有执行路径

## Open Questions

- 是否需要为不同 provider 配置不同的 max_retries？（当前建议统一配置，后续按需扩展）
