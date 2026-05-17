## Why

Pipeline 在批量分析时因 LLM 调用失败（网络超时、服务端错误或返回格式异常）导致整条流水线中断或单条数据报废，已消耗的 tokens 被浪费。需要在 LLM 调用层增加健壮的重试机制，提高单条分析成功率，避免重复采集成本。

## What Changes

- **增强 `chat_with_retry()`**: 扩展可重试错误范围，除网络错误外，增加 LLM 返回内容格式异常（`json.JSONDecodeError`、字段缺失）的重试逻辑
- **新增内容级校验重试**: 在 `analyze_item()` 中对 LLM 输出进行 schema 校验，校验失败时触发重试而非直接返回 None
- **优化退避策略**: 解析 HTTP 429 响应的 `Retry-After` header，优先使用服务端建议的等待时间
- **增强可观测性**: 在 `Usage` 中记录重试次数，在 pipeline 统计中输出平均重试次数和失败明细
- **新增断点续跑支持**: 基于 URL 对已分析条目进行去重，避免中断后重新分析已消费过 tokens 的数据

## Capabilities

### New Capabilities
- `llm-retry`: LLM 调用层的重试策略与错误恢复机制，覆盖网络错误和内容格式错误

### Modified Capabilities
<!-- 无现有 spec 需要修改 -->

## Impact

- **pipeline/model_client.py**: `chat_with_retry()` 和 `Usage` 类
- **pipeline/pipeline.py**: `analyze_item()` 和 `run_pipeline()` 的统计逻辑
- **knowledge/articles/**: 可能因断点续跑产生部分写入的文件，不影响现有数据格式
- **CLI 输出**: 统计报告新增重试相关指标
