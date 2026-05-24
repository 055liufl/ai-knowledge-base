"""Router 路由模式：两层意图分类与分发。

实现一个意图路由器，通过关键词快速匹配 + LLM 兜底分类，
将用户查询分发到对应的处理器。

处理器：
    - github_search: 调用 GitHub Search API 搜索仓库
    - knowledge_query: 从本地知识库检索相关文章
    - general_chat: 调用 LLM 进行通用对话

编码规范：
    - 严格遵循 PEP 8
    - 使用 Google 风格 docstring
    - 使用 logging 而非 print
"""

from __future__ import annotations

import json
import logging
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

# 确保项目根目录在 sys.path 中，支持直接运行本文件
_PROJECT_ROOT = Path(__file__).parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from workflows.model_client import chat, chat_json

logger = logging.getLogger(__name__)

_INTENT_GITHUB_SEARCH = "github_search"
_INTENT_KNOWLEDGE_QUERY = "knowledge_query"
_INTENT_GENERAL_CHAT = "general_chat"

_INTENTS = [_INTENT_GITHUB_SEARCH, _INTENT_KNOWLEDGE_QUERY, _INTENT_GENERAL_CHAT]

# 第一层：关键词快速匹配规则
# 优先级：github > knowledge > general（兜底）
_KEYWORD_MAP: dict[str, list[str]] = {
    _INTENT_GITHUB_SEARCH: [
        "github", "repo", "repository", "star", "fork",
        "项目", "仓库", "开源",
    ],
    _INTENT_KNOWLEDGE_QUERY: [
        "知识", "文章", "论文", "article", "paper",
        "knowledge", "rss", "arxiv", "summary",
    ],
}

_GITHUB_SEARCH_API = "https://api.github.com/search/repositories"
_KNOWLEDGE_DIR = Path(__file__).parent.parent / "knowledge" / "articles"


def _classify_by_keyword(query: str) -> str | None:
    """第一层：基于关键词的零成本意图分类。

    将查询转为小写，依次匹配各意图的关键词列表。
    匹配到第一个即返回，无匹配返回 None。

    Args:
        query: 用户输入的查询文本。

    Returns:
        str | None: 匹配到的意图标识，或 None 表示需要 LLM 兜底。
    """
    lower_query = query.lower()
    for intent, keywords in _KEYWORD_MAP.items():
        for keyword in keywords:
            if keyword in lower_query:
                logger.debug("关键词命中: intent=%s, keyword=%s", intent, keyword)
                return intent
    return None


def _classify_by_llm(query: str) -> str:
    """第二层：LLM 兜底分类。

    当关键词无法确定意图时，调用 LLM 进行分类。

    Args:
        query: 用户输入的查询文本。

    Returns:
        str: LLM 判定的意图标识，无效时返回 general_chat。
    """
    system_prompt = (
        "你是一个意图分类器。请将用户查询分类为以下三种意图之一：\n"
        "- github_search: 用户想搜索 GitHub 上的开源项目、仓库、代码\n"
        "- knowledge_query: 用户想查询知识库中的文章、论文、摘要、技术资讯\n"
        "- general_chat: 一般的闲聊、问答、非特定领域的对话\n\n"
        "只返回意图标识字符串，不要解释。"
    )

    try:
        text, usage = chat(
            prompt=query,
            system_prompt=system_prompt,
            temperature=0.1,
            max_tokens=20,
        )
        intent = text.strip().lower()
        logger.info(
            "LLM 分类结果: intent=%s, prompt_tokens=%d, completion_tokens=%d",
            intent,
            usage.prompt_tokens,
            usage.completion_tokens,
        )
        if intent in _INTENTS:
            return intent
        return _INTENT_GENERAL_CHAT
    except Exception as exc:
        logger.error("LLM 分类失败: %s", exc)
        return _INTENT_GENERAL_CHAT


def _handle_github_search(query: str) -> str:
    """处理 GitHub 搜索意图。

    使用 urllib 调用 GitHub Search API，返回格式化结果。
    query 参数使用 urllib.parse.quote 编码，支持中文与空格。

    Args:
        query: 用户输入的查询文本。

    Returns:
        str: 搜索结果摘要或错误信息。
    """
    # 去除意图关键词和通用查询词，提取有效搜索词
    noise_words = [
        "repo", "repository", "star", "fork",
        "项目", "仓库", "开源",
        "搜索", "查找", "推荐", "最近", "热门", "最好", "好用",
        "几个", "一些", "有没有", "哪些",
        "的", "了", "是", "有",
    ]
    search_term = query.lower()
    for word in noise_words:
        search_term = search_term.replace(word, " ")
    search_term = " ".join(search_term.split())

    # GitHub 主要索引英文，优先提取英文/技术关键词
    import re
    english_terms = re.findall(r"[a-z0-9]+(?:[\-\._][a-z0-9]+)*", search_term)
    if english_terms:
        search_term = " ".join(english_terms)
    elif not search_term.strip():
        # 过滤后无有效词，尝试从原始查询提取英文词
        original_terms = re.findall(
            r"[a-z0-9]+(?:[\-\._][a-z0-9]+)*", query.lower()
        )
        if original_terms:
            search_term = " ".join(original_terms)
        else:
            # 纯中文查询，返回 GitHub 热门仓库
            search_term = "stars:>1000"

    encoded = urllib.parse.quote(search_term)
    url = f"{_GITHUB_SEARCH_API}?q={encoded}&sort=stars&order=desc&per_page=5"

    logger.info("GitHub API 请求: %s", url)

    try:
        req = urllib.request.Request(
            url,
            headers={
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": "Router-Pattern/1.0",
            },
        )
        with urllib.request.urlopen(req, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))

        items = data.get("items", [])
        if not items:
            return f"未找到与 '{search_term}' 相关的 GitHub 仓库。"

        lines = [f"GitHub 搜索结果（'{search_term}'）："]
        for idx, item in enumerate(items[:5], 1):
            lines.append(
                f"{idx}. {item['full_name']} "
                f"⭐{item.get('stargazers_count', 0)}\n"
                f"   {item.get('description', '无描述')}\n"
                f"   {item.get('html_url', '')}"
            )
        return "\n\n".join(lines)

    except urllib.error.HTTPError as exc:
        logger.error("GitHub API HTTP 错误 %d: %s", exc.code, exc.reason)
        return f"GitHub API 错误: {exc.code} {exc.reason}"
    except urllib.error.URLError as exc:
        logger.error("GitHub API 网络错误: %s", exc.reason)
        return f"无法连接到 GitHub API: {exc.reason}"
    except Exception as exc:
        logger.error("GitHub 搜索异常: %s", exc)
        return f"搜索失败: {exc}"


def _handle_knowledge_query(query: str) -> str:
    """处理知识库查询意图。

    扫描本地 knowledge/articles/ 目录，按标题和标签匹配相关文章。

    Args:
        query: 用户输入的查询文本。

    Returns:
        str: 检索结果摘要或提示信息。
    """
    if not _KNOWLEDGE_DIR.exists():
        return "知识库目录不存在，请先采集文章。"

    query_lower = query.lower()
    matches: list[tuple[float, dict[str, Any]]] = []

    try:
        for file_path in _KNOWLEDGE_DIR.glob("*.json"):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    article = json.load(f)

                score = 0.0
                title = article.get("title", "")
                tags = article.get("tags", [])
                summary = article.get("summary", "")

                # 标题匹配权重最高
                if any(word in title.lower() for word in query_lower.split()):
                    score += 10.0

                # 标签匹配
                for tag in tags:
                    if tag.lower() in query_lower:
                        score += 5.0

                # 摘要匹配
                if any(word in summary.lower() for word in query_lower.split()):
                    score += 2.0

                if score > 0:
                    matches.append((score, article))

            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("读取文章失败 %s: %s", file_path, exc)
                continue

        if not matches:
            return f"知识库中未找到与 '{query}' 相关的文章。"

        # 按得分降序排列，取前 5 篇
        matches.sort(key=lambda x: x[0], reverse=True)
        top_matches = matches[:5]

        lines = [f"知识库检索结果（'{query}'）："]
        for idx, (score, article) in enumerate(top_matches, 1):
            title = article.get("title", "无标题")
            source = article.get("source_platform", "unknown")
            url = article.get("source_url", "")
            summary = article.get("summary", "")[:150]
            tags = ", ".join(article.get("tags", [])[:5])
            lines.append(
                f"{idx}. [{title}] (相关度: {score:.1f})\n"
                f"   来源: {source} | 标签: {tags}\n"
                f"   摘要: {summary}...\n"
                f"   链接: {url}"
            )

        return "\n\n".join(lines)

    except Exception as exc:
        logger.error("知识库查询异常: %s", exc)
        return f"知识库查询失败: {exc}"


def _handle_general_chat(query: str) -> str:
    """处理通用对话意图。

    直接调用 LLM 回答用户问题。

    Args:
        query: 用户输入的查询文本。

    Returns:
        str: LLM 生成的回答。
    """
    system_prompt = (
        "你是一个乐于助人的 AI 助手。请用简洁、准确的中文回答用户的问题。"
    )

    try:
        text, usage = chat(
            prompt=query,
            system_prompt=system_prompt,
        )
        logger.info(
            "通用对话完成: prompt_tokens=%d, completion_tokens=%d",
            usage.prompt_tokens,
            usage.completion_tokens,
        )
        return text
    except Exception as exc:
        logger.error("通用对话异常: %s", exc)
        return f"对话服务暂时不可用: {exc}"


# 意图到处理器的映射
_HANDLERS: dict[str, Any] = {
    _INTENT_GITHUB_SEARCH: _handle_github_search,
    _INTENT_KNOWLEDGE_QUERY: _handle_knowledge_query,
    _INTENT_GENERAL_CHAT: _handle_general_chat,
}


def route(query: str) -> str:
    """统一路由入口。

    执行两层意图分类，将查询分发到对应处理器。

    Args:
        query: 用户输入的查询文本。

    Returns:
        str: 处理器返回的结果文本。

    Example:
        >>> result = route("推荐几个热门的 Python 项目")
        >>> print(result)
    """
    if not query or not query.strip():
        return "请输入您的问题。"

    query = query.strip()
    logger.info("收到查询: %s", query)

    # 第一层：关键词快速匹配
    intent = _classify_by_keyword(query)

    # 第二层：LLM 兜底
    if intent is None:
        logger.info("关键词未命中，进入 LLM 分类")
        intent = _classify_by_llm(query)

    logger.info("最终意图: %s", intent)

    handler = _HANDLERS.get(intent, _handle_general_chat)
    return handler(query)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # 支持命令行传参：python3 -m patterns.router "查询内容"
    if len(sys.argv) > 1:
        query = sys.argv[1]
        print(route(query))
        sys.exit(0)

    # 无参数时运行默认测试用例
    test_queries = [
        "推荐几个热门的 Python 项目",
        "github 上有哪些好用的 AI 工具",
        "搜索 star 最多的 transformer 仓库",
        "查找关于 RAG 的文章",
        "有没有关于 Agent 的论文",
        "knowledge 里 LLM 相关的资讯",
        "今天天气怎么样",
        "1+1 等于几",
        "解释一下什么是大语言模型",
        "",
        "github",
    ]

    print("=" * 60)
    print("Router 路由模式测试")
    print("=" * 60)

    for q in test_queries:
        print(f"\n{'─' * 60}")
        print(f"查询: {q!r}")
        print(f"{'─' * 60}")
        try:
            result = route(q)
            print(f"结果:\n{result}")
        except Exception as exc:
            print(f"异常: {exc}")

    print(f"\n{'=' * 60}")
    print("测试结束")
    print("=" * 60)
