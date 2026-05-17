## 1. 新增 with_retry 装饰器

- [ ] 1.1 在 `pipeline/model_client.py` 中实现 `with_retry` 装饰器，支持 `max_attempts`、`base_delay`、`max_delay` 参数
- [ ] 1.2 实现指数退避 + jitter（1.0-1.5× 只加不减）
- [ ] 1.3 实现可重试异常白名单：`httpx.TimeoutException`、`httpx.ConnectError`、`RateLimitError`、`APIStatusError(status>=500)`
- [ ] 1.4 不可重试异常直接抛出：`json.JSONDecodeError`、`KeyError`、`ValueError`
- [ ] 1.5 将 `with_retry` 装饰器应用到 `OpenAICompatibleProvider.chat()` 方法

## 2. 成本追踪

- [ ] 2.1 在 `with_retry` 内实现 cost_tracker：每次 API 调用（含失败重试）记录一次
- [ ] 2.2 失败尝试记录 `prompt_tokens=0, completion_tokens=0`
- [ ] 2.3 成功尝试按 `response.usage` 记录实际 tokens
- [ ] 2.4 将 cost_tracker 日志输出到 `logger.info`

## 3. Graceful Degradation

- [ ] 3.1 在 `pipeline/pipeline.py::analyze_item()` 中捕获终极失败（`with_retry` 耗尽后的异常）
- [ ] 3.2 失败时用 `raw_content[:200]` 作为降级 summary
- [ ] 3.3 在 `pipeline/pipeline.py::standardize()` 中，当 `analysis` 为 `None`（降级情况）时设置 `status="degraded"`
- [ ] 3.4 确保降级后 pipeline 继续处理剩余 items，不中断

## 4. 验证

- [ ] 4.1 运行 `python -m py_compile pipeline/model_client.py` 确认无语法错误
- [ ] 4.2 运行 `python -m py_compile pipeline/pipeline.py` 确认无语法错误
- [ ] 4.3 运行 `python pipeline/pipeline.py --dry-run --limit 5` 确认 pipeline 能正常跑完
- [ ] 4.4 检查生成的 article JSON 中 `status` 字段正确（成功为 `"pending"`，降级为 `"degraded"`）
