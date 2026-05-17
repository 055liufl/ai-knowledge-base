## 1. 参数与配置调整

- [ ] 1.1 修改全局默认常量：`timeout=30.0`，`max_retries=2`，`base_delay=2.0`
- [ ] 1.2 在 `_PROVIDER_CONFIG` 的 deepseek/qwen/openai 配置下各增加 `retry_policy` 字段
- [ ] 1.3 在 `OpenAICompatibleProvider.__init__` 中读取并保存 `retry_policy`，缺失时回退到全局默认值

## 2. 重试逻辑重构

- [ ] 2.1 重构 `chat_with_retry` 的异常捕获逻辑：区分 `ConnectTimeout`/`ConnectError`/`ReadTimeout`
- [ ] 2.2 实现 `ReadTimeout` 最多重试 1 次的独立计数逻辑
- [ ] 2.3 实现 HTTP 状态码白名单：只重试 429/502/503/504，客户端错误直接抛出
- [ ] 2.4 实现 429 响应的 `Retry-After` 头读取，优先于指数退避计算
- [ ] 2.5 更新 `chat_with_retry` 的 docstring 以反映新的重试行为

## 3. 验证与测试

- [ ] 3.1 运行 `python pipeline/pipeline.py --dry-run --limit 5` 确认 pipeline 层无需修改即可正常工作
- [ ] 3.2 运行 `python pipeline/model_client.py` 本地测试（无需有效 API Key 的部分）确认无语法错误
- [ ] 3.3 检查 `lsp_diagnostics` 或 `python -m py_compile pipeline/model_client.py` 确认无类型/语法错误
- [ ] 3.4 验证 `chat_with_retry` 的默认参数值符合 spec（timeout=30, max_retries=2）
