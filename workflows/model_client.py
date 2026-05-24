"""LLM 客户端适配器。

对 pipeline.model_client 的轻量封装，提供 chat() 和 chat_json() 便捷函数。

编码规范：
    - 严格遵循 PEP 8
    - 使用 Google 风格 docstring
    - 使用 logging 而非 print
"""

from __future__ import annotations

import json
import os
import logging
from typing import Any

from pipeline.model_client import chat_with_retry, quick_chat, Usage

# ── 全局 CostGuard（懒加载）─────────────────────────────────
_cost_guard_instance = None


def get_cost_guard():
    """获取全局 CostGuard 实例（懒加载）。

    第一次调用时创建实例，后续复用同一实例。
    budget_yuan 从环境变量 BUDGET_YUAN 读取，默认 1.0。

    Returns:
        CostGuard: 全局 CostGuard 实例。
    """
    global _cost_guard_instance
    if _cost_guard_instance is None:
        try:
            from tests.cost_guard import CostGuard
        except ImportError:
            from cost_guard import CostGuard

        budget = float(os.environ.get("BUDGET_YUAN", "1.0"))
        _cost_guard_instance = CostGuard(budget_yuan=budget)
        logger.info(
            "[model_client] CostGuard 初始化: budget_yuan=%.4f",
            budget,
        )
    return _cost_guard_instance


logger = logging.getLogger(__name__)


def chat(
    prompt: str,
    system_prompt: str | None = None,
    provider_name: str | None = None,
    node_name: str = "unknown",
    model: str | None = None,
    temperature: float = 0.7,
    max_tokens: int | None = None,
    **kwargs: Any,
) -> tuple[str, Usage]:
    """调用 LLM 返回纯文本和用量统计。

    Args:
        prompt: 用户输入的提示文本。
        system_prompt: 可选的系统提示词。
        provider_name: 提供商名称，默认从环境变量读取。
        node_name: 调用来源节点名称，用于成本追踪。
        model: 模型名称，默认使用提供商默认。
        temperature: 采样温度。
        max_tokens: 最大生成 Token 数。
        **kwargs: 传给 chat_with_retry 的其他参数。

    Returns:
        tuple[str, Usage]: (生成的文本内容, Token 用量统计)。
    """
    messages: list[dict[str, str]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    response = chat_with_retry(
        messages=messages,
        provider_name=provider_name,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        **kwargs,
    )

    logger.debug(
        "chat 调用成功: model=%s, prompt_tokens=%d, completion_tokens=%d",
        response.model,
        response.usage.prompt_tokens,
        response.usage.completion_tokens,
    )

    # ── 记录成本并检查预算 ──────────────────────────────────
    try:
        cost_guard = get_cost_guard()
        usage_dict = {
            "prompt_tokens": response.usage.prompt_tokens,
            "completion_tokens": response.usage.completion_tokens,
        }
        cost_guard.record(
            node_name=node_name,
            usage=usage_dict,
            model=response.model or model or "unknown",
        )
        cost_guard.check()
    except Exception as exc:
        # BudgetExceededError 需要向上抛出，其他异常只记录日志
        if "预算" in str(exc) or "Budget" in type(exc).__name__:
            raise
        logger.warning("[model_client] 成本记录异常: %s", exc)

    return response.content, response.usage


def chat_json(
    prompt: str,
    system_prompt: str | None = None,
    provider_name: str | None = None,
    node_name: str = "unknown",
    model: str | None = None,
    temperature: float = 0.7,
    max_tokens: int | None = None,
    **kwargs: Any,
) -> tuple[dict[str, Any], Usage]:
    """调用 LLM 并尝试将响应解析为 JSON。

    在 prompt 中自动附加 JSON 格式要求，并尝试解析返回内容。
    如果解析失败，返回包含 error 和 raw_content 的字典。

    Args:
        prompt: 用户输入的提示文本。
        system_prompt: 可选的系统提示词。
        provider_name: 提供商名称，默认从环境变量读取。
        node_name: 调用来源节点名称，透传给 chat()。
        model: 模型名称，默认使用提供商默认。
        temperature: 采样温度。
        max_tokens: 最大生成 Token 数。
        **kwargs: 传给 chat_with_retry 的其他参数。

    Returns:
        tuple[dict[str, Any], Usage]: (解析后的 JSON 字典, Token 用量统计)。
    """
    json_system_prompt = (
        "你必须以纯 JSON 格式返回结果，不要包含任何 markdown 代码块标记（如 ```json），"
        "直接返回可解析的 JSON 字符串。"
    )

    full_system_prompt = json_system_prompt
    if system_prompt:
        full_system_prompt = f"{system_prompt}\n\n{json_system_prompt}"

    text, usage = chat(
        prompt=prompt,
        system_prompt=full_system_prompt,
        node_name=node_name,
        provider_name=provider_name,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        **kwargs,
    )

    # 清理可能的 markdown 代码块
    cleaned = text.strip()
    if cleaned.startswith("```"):
        # 移除开头的 ```json 或 ```
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned
        # 移除结尾的 ```
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3].strip()

    try:
        result = json.loads(cleaned)
        logger.debug("JSON 解析成功: keys=%s", list(result.keys()))
        return result, usage
    except json.JSONDecodeError as exc:
        logger.warning("JSON 解析失败: %s, raw_content=%s", exc, text[:200])
        return {
            "error": f"JSON 解析失败: {exc}",
            "raw_content": text,
        }, usage
