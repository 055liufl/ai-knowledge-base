"""统一的 LLM 调用客户端。

支持 DeepSeek、Qwen、OpenAI 三种模型提供商，通过环境变量切换，
使用 httpx 直接调用 OpenAI 兼容 API。

编码规范：
    - 严格遵循 PEP 8
    - 使用 Google 风格 docstring
    - 使用 logging 而非 print
"""

from __future__ import annotations

import abc
import logging
import os
import random
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 60.0
_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 1.0
_RETRY_MAX_JITTER = 0.5

_CHAR_PER_TOKEN = 4.0

_PROVIDER_CONFIG: dict[str, dict[str, Any]] = {
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "api_key_env": "DEEPSEEK_API_KEY",
        "default_model": "deepseek-chat",
        "models": {
            "deepseek-chat": {"input_price": 0.14, "output_price": 0.28},
            "deepseek-coder": {"input_price": 0.14, "output_price": 0.28},
        },
    },
    "qwen": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "api_key_env": "QWEN_API_KEY",
        "default_model": "qwen-max",
        "models": {
            "qwen-max": {"input_price": 5.0, "output_price": 10.0},
            "qwen-plus": {"input_price": 2.0, "output_price": 6.0},
            "qwen-turbo": {"input_price": 0.5, "output_price": 2.0},
        },
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "api_key_env": "OPENAI_API_KEY",
        "default_model": "gpt-4o",
        "models": {
            "gpt-4o": {"input_price": 2.5, "output_price": 10.0},
            "gpt-4o-mini": {"input_price": 0.15, "output_price": 0.6},
            "gpt-4-turbo": {"input_price": 10.0, "output_price": 30.0},
        },
    },
}


@dataclass
class Usage:
    """LLM API 用量统计。

    Attributes:
        prompt_tokens: 输入 Token 数量。
        completion_tokens: 输出 Token 数量。
        total_tokens: 总 Token 数量。
    """

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class LLMResponse:
    """统一的 LLM 响应封装。

    Attributes:
        content: 模型生成的文本内容。
        usage: Token 用量统计。
        model: 实际使用的模型名称。
        provider: 使用的提供商标识。
    """

    content: str
    usage: Usage = field(default_factory=Usage)
    model: str = ""
    provider: str = ""


class LLMProvider(abc.ABC):
    """LLM 提供商抽象基类。

    定义所有 LLM 提供商必须实现的接口。
    """

    @abc.abstractmethod
    def chat(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """发送聊天请求到 LLM。

        Args:
            messages: OpenAI 格式的消息列表，例如
                [{"role": "user", "content": "你好"}]。
            model: 模型名称，None 则使用提供商默认模型。
            temperature: 采样温度，默认 0.7。
            max_tokens: 最大生成 Token 数，默认 None。
            **kwargs: 额外的 API 参数。

        Returns:
            LLMResponse: 包含生成内容和用量统计。

        Raises:
            httpx.HTTPStatusError: 当 API 返回非 2xx 状态码时。
            httpx.TimeoutException: 当请求超时时。
        """
        ...

    @abc.abstractmethod
    def estimate_tokens(self, text: str) -> int:
        """估算文本的 Token 数量。

        Args:
            text: 需要估算的文本。

        Returns:
            int: 估算的 Token 数量（基于字符数 / 4 的粗略估算）。
        """
        ...

    @abc.abstractmethod
    def calculate_cost(
        self,
        prompt_tokens: int,
        completion_tokens: int,
        model: str | None = None,
    ) -> float:
        """计算 API 调用的预估成本（USD）。

        Args:
            prompt_tokens: 输入 Token 数量。
            completion_tokens: 输出 Token 数量。
            model: 模型名称，None 则使用默认模型。

        Returns:
            float: 预估成本，单位 USD。
        """
        ...


class OpenAICompatibleProvider(LLMProvider):
    """基于 OpenAI 兼容 API 的通用 LLM 提供商。

    通过标准 HTTP 接口支持 DeepSeek、Qwen、OpenAI 等提供商，
    无需依赖 openai SDK。

    Attributes:
        provider_name: 提供商标识（deepseek / qwen / openai）。
        model: 当前使用的模型名称。
    """

    def __init__(self, provider_name: str | None = None, model: str | None = None) -> None:
        """初始化提供商。

        Args:
            provider_name: 提供商名称。None 则从环境变量 LLM_PROVIDER 读取，
                默认为 deepseek。
            model: 模型名称。None 则使用提供商配置的默认模型。

        Raises:
            ValueError: 当提供商名称无效或缺少 API Key 时。
        """
        self.provider_name = (
            provider_name or os.getenv("LLM_PROVIDER", "deepseek").lower().strip()
        )

        if self.provider_name not in _PROVIDER_CONFIG:
            valid = ", ".join(_PROVIDER_CONFIG.keys())
            raise ValueError(
                f"不支持的 LLM 提供商: {self.provider_name}. "
                f"有效选项: {valid}"
            )

        self._config = _PROVIDER_CONFIG[self.provider_name]
        self._api_key = os.getenv(self._config["api_key_env"], "")
        if not self._api_key:
            raise ValueError(
                f"缺少 API Key: 请设置环境变量 {self._config['api_key_env']}"
            )

        self.model = model or self._config["default_model"]
        self._base_url = self._config["base_url"].rstrip("/")
        self._client = httpx.Client(
            timeout=_DEFAULT_TIMEOUT,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
        )

        logger.info(
            "初始化 LLM 提供商: provider=%s, model=%s, base_url=%s",
            self.provider_name,
            self.model,
            self._base_url,
        )

    def chat(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """发送聊天请求。

        直接通过 HTTP POST /chat/completions 调用模型。

        Args:
            messages: OpenAI 格式的消息列表。
            model: 覆盖当前实例的模型名称。
            temperature: 采样温度。
            max_tokens: 最大生成 Token 数。
            **kwargs: 额外参数（如 top_p, frequency_penalty 等）。

        Returns:
            LLMResponse: 解析后的响应对象。

        Raises:
            httpx.HTTPStatusError: API 返回错误状态码。
            httpx.TimeoutException: 请求超时。
            ValueError: 响应格式异常。
        """
        target_model = model or self.model
        payload: dict[str, Any] = {
            "model": target_model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        payload.update(kwargs)

        url = f"{self._base_url}/chat/completions"
        logger.debug(
            "发送请求: url=%s, model=%s, messages_count=%d",
            url,
            target_model,
            len(messages),
        )

        response = self._client.post(url, json=payload)
        response.raise_for_status()
        data = response.json()

        try:
            choice = data["choices"][0]
            message = choice["message"]
            content = message.get("content", "")

            usage_data = data.get("usage", {})
            usage = Usage(
                prompt_tokens=usage_data.get("prompt_tokens", 0),
                completion_tokens=usage_data.get("completion_tokens", 0),
                total_tokens=usage_data.get("total_tokens", 0),
            )

            logger.info(
                "请求成功: model=%s, prompt_tokens=%d, completion_tokens=%d",
                target_model,
                usage.prompt_tokens,
                usage.completion_tokens,
            )

            return LLMResponse(
                content=content,
                usage=usage,
                model=target_model,
                provider=self.provider_name,
            )
        except (KeyError, IndexError) as exc:
            logger.error("解析响应失败: %s", data)
            raise ValueError(f"无效的 API 响应格式: {exc}") from exc

    def estimate_tokens(self, text: str) -> int:
        """基于字符数的粗略 Token 估算。

        采用 4 字符 ≈ 1 Token 的简化估算，适用于中英文混合文本的
        快速成本预估。注意：实际 Token 数可能因 tokenizer 差异而不同。

        Args:
            text: 待估算文本。

        Returns:
            int: 向上取整的估算 Token 数。
        """
        return max(1, int(len(text) / _CHAR_PER_TOKEN + 0.5))

    def calculate_cost(
        self,
        prompt_tokens: int,
        completion_tokens: int,
        model: str | None = None,
    ) -> float:
        """计算预估 API 成本（USD / 1M tokens）。

        Args:
            prompt_tokens: 输入 Token 数量。
            completion_tokens: 输出 Token 数量。
            model: 模型名称，默认使用当前实例模型。

        Returns:
            float: 总成本（USD）。

        Raises:
            KeyError: 当指定模型的价格未配置时。
        """
        target_model = model or self.model
        model_config = self._config["models"].get(target_model)
        if model_config is None:
            raise KeyError(
                f"未找到模型 {target_model} 的价格配置，"
                f"已配置: {list(self._config['models'].keys())}"
            )

        input_cost = prompt_tokens * model_config["input_price"] / 1_000_000
        output_cost = completion_tokens * model_config["output_price"] / 1_000_000
        total = round(input_cost + output_cost, 6)

        logger.debug(
            "成本估算: model=%s, input=%d, output=%d, cost=%.6f USD",
            target_model,
            prompt_tokens,
            completion_tokens,
            total,
        )
        return total

    def close(self) -> None:
        """关闭底层 HTTP 客户端，释放连接资源。"""
        self._client.close()
        logger.debug("关闭 %s HTTP 客户端", self.provider_name)

    def __enter__(self) -> OpenAICompatibleProvider:
        """支持 with 语句上下文管理。"""
        return self

    def __exit__(self, *args: Any) -> None:
        """退出上下文时自动关闭客户端。"""
        self.close()


def chat_with_retry(
    messages: list[dict[str, str]],
    provider_name: str | None = None,
    model: str | None = None,
    temperature: float = 0.7,
    max_tokens: int | None = None,
    max_retries: int = _MAX_RETRIES,
    timeout: float = _DEFAULT_TIMEOUT,
    **kwargs: Any,
) -> LLMResponse:
    """带指数退避重试的聊天请求。

    当遇到网络超时、速率限制（429）或服务器错误（5xx）时，
    自动重试最多指定次数，每次延迟指数增长并添加随机抖动。

    Args:
        messages: OpenAI 格式的消息列表。
        provider_name: 提供商名称，None 则从环境变量读取。
        model: 模型名称，None 则使用默认。
        temperature: 采样温度。
        max_tokens: 最大生成 Token 数。
        max_retries: 最大重试次数，默认 3。
        timeout: 单次请求超时秒数，默认 60。
        **kwargs: 额外 API 参数。

    Returns:
        LLMResponse: 成功时的响应对象。

    Raises:
        httpx.HTTPStatusError: 当非可重试错误（如 4xx 客户端错误）时。
        RuntimeError: 当所有重试耗尽后仍失败时。
    """
    provider = OpenAICompatibleProvider(provider_name=provider_name, model=model)

    if timeout != _DEFAULT_TIMEOUT:
        provider._client.timeout = httpx.Timeout(timeout)

    last_exception: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            logger.info(
                "请求尝试 %d/%d: provider=%s, model=%s",
                attempt + 1,
                max_retries + 1,
                provider.provider_name,
                provider.model,
            )
            response = provider.chat(
                messages=messages,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs,
            )
            return response
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            last_exception = exc
            logger.warning(
                "尝试 %d 失败（网络）: %s", attempt + 1, exc
            )
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            if status_code == 429 or status_code >= 500:
                last_exception = exc
                logger.warning(
                    "尝试 %d 失败（HTTP %d）: %s",
                    attempt + 1,
                    status_code,
                    exc,
                )
            else:
                logger.error("客户端错误 %d，放弃重试", status_code)
                raise

        if attempt < max_retries:
            delay = _RETRY_BASE_DELAY * (2**attempt) + random.uniform(
                0, _RETRY_MAX_JITTER
            )
            logger.info("等待 %.2f 秒后重试...", delay)
            time.sleep(delay)

    raise RuntimeError(
        f"在 {max_retries + 1} 次尝试后仍未能成功调用 LLM"
    ) from last_exception


def quick_chat(
    prompt: str,
    system_prompt: str | None = None,
    provider_name: str | None = None,
    model: str | None = None,
    **kwargs: Any,
) -> str:
    """一句话调用 LLM，返回纯文本内容。

    最简化的 LLM 调用方式，自动构建消息列表并返回 content 字符串。

    Args:
        prompt: 用户输入的提示文本。
        system_prompt: 可选的系统提示词。
        provider_name: 提供商名称，默认从环境变量读取。
        model: 模型名称，默认使用提供商默认。
        **kwargs: 传给 chat_with_retry 的其他参数。

    Returns:
        str: 模型生成的文本内容。

    Example:
        >>> reply = quick_chat("请用一句话介绍 Python")
        >>> print(reply)
        Python 是一种高级、解释型、通用的编程语言...
    """
    messages: list[dict[str, str]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    response = chat_with_retry(
        messages=messages,
        provider_name=provider_name,
        model=model,
        **kwargs,
    )
    return response.content


def get_provider(
    provider_name: str | None = None, model: str | None = None
) -> OpenAICompatibleProvider:
    """获取一个配置好的 LLMProvider 实例。

    Args:
        provider_name: 提供商名称。默认 deepseek。
        model: 模型名称。

    Returns:
        OpenAICompatibleProvider: 配置完成的提供商实例。
    """
    return OpenAICompatibleProvider(provider_name=provider_name, model=model)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    logger.info("=== model_client.py 本地测试 ===")

    try:
        os.environ.setdefault("DEEPSEEK_API_KEY", "test-key-for-init")
        provider = OpenAICompatibleProvider(provider_name="deepseek")

        sample_text = "Python 是一种高级、解释型、通用的编程语言。"
        estimated = provider.estimate_tokens(sample_text)
        logger.info("Token 估算测试: text='%s...', estimated_tokens=%d", sample_text[:20], estimated)

        cost = provider.calculate_cost(
            prompt_tokens=1000,
            completion_tokens=500,
            model="deepseek-chat",
        )
        logger.info("成本计算测试: 1000 in + 500 out = %.6f USD", cost)
        provider.close()
    except Exception as exc:
        logger.error("本地测试失败: %s", exc)

    logger.info("=== 开始 API 调用测试（需要有效的 API Key） ===")

    test_messages = [
        {"role": "system", "content": "你是一个乐于助人的助手。"},
        {"role": "user", "content": "请用一句话介绍你自己。"},
    ]

    try:
        response = chat_with_retry(
            messages=test_messages,
            max_retries=1,
            temperature=0.7,
        )
        logger.info("API 调用成功!")
        logger.info("模型: %s", response.model)
        logger.info("内容: %s", response.content[:200])
        logger.info(
            "用量: prompt=%d, completion=%d, total=%d",
            response.usage.prompt_tokens,
            response.usage.completion_tokens,
            response.usage.total_tokens,
        )
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 401:
            logger.warning("API Key 无效或过期（401），跳过 API 调用测试")
        else:
            logger.error("HTTP 错误 %d: %s", exc.response.status_code, exc)
    except ValueError as exc:
        logger.error("配置错误: %s", exc)
    except RuntimeError as exc:
        logger.error("API 调用失败（已重试）: %s", exc)
    except Exception as exc:
        logger.error("未预期的错误: %s", exc)

    try:
        reply = quick_chat(
            prompt="1+1=？只回答数字。",
            system_prompt="你只会回答数字。",
            max_retries=1,
        )
        logger.info("quick_chat 测试成功: %s", reply[:100])
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 401:
            logger.warning("API Key 无效（401），跳过 quick_chat 测试")
        else:
            logger.error("quick_chat HTTP 错误: %s", exc)
    except Exception as exc:
        logger.error("quick_chat 测试失败: %s", exc)

    logger.info("=== 测试结束 ===")
