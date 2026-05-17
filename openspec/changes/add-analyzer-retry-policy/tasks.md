## 1. model_client.py - 增强重试机制

- [x] 1.1 扩展 `Usage` dataclass，增加 `retry_count: int = 0` 字段
- [x] 1.2 修改 `chat_with_retry()` 签名，增加可选 `validator: Callable[[str], None] | None = None` 参数
- [x] 1.3 在 `chat_with_retry()` 中实现内容校验重试逻辑：当 HTTP 200 但 validator 抛出异常时，按网络错误相同的退避策略重试
- [x] 1.4 增强 429 处理：解析 `Retry-After` header，设置上限 60 秒，超过则回退指数退避
- [x] 1.5 确保每次重试的 `retry_count` 被正确累加并写入最终 `LLMResponse.usage`

## 2. pipeline.py - 内容校验与断点续跑

- [x] 2.1 在 `analyze_item()` 中实现 JSON schema 校验函数，校验必填字段和类型
- [x] 2.2 修改 `analyze_item()` 调用 `quick_chat()` 时传入 validator，触发内容错误重试
- [x] 2.3 实现 `_is_already_analyzed(url: str) -> bool` 函数，扫描 `knowledge/articles/` 检查 URL 是否已存在
- [x] 2.4 在 `run_pipeline()` 的分析循环中，调用 `analyze_item()` 前检查 `_is_already_analyzed()`，若存在则跳过

## 3. 统计与可观测性

- [x] 3.1 修改 `run_pipeline()` 的 `stats` 结构，增加 `total_retries` 和 `failed_items` 明细
- [x] 3.2 在分析循环中累加每条目的 `usage.retry_count` 到 `total_retries`
- [x] 3.3 增强最终统计输出，显示平均重试次数和失败条目明细（标题 + 错误原因）

## 4. 验证

- [x] 4.1 编写本地测试：模拟 HTTP 超时，验证重试 3 次后失败
- [x] 4.2 编写本地测试：模拟 HTTP 429 返回 Retry-After: 2，验证等待时间正确
- [x] 4.3 编写本地测试：模拟 LLM 返回无效 JSON，验证触发内容重试
- [x] 4.4 断点续跑测试：中断后重新运行，验证已分析 URL 被跳过
- [x] 4.5 运行完整 pipeline dry-run，验证统计输出格式正确
