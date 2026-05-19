"""四步知识库自动化流水线。

提供从数据采集、LLM 分析、整理去重到持久化的完整工作流，
支持 GitHub Search API 和 RSS 源，通过 CLI 灵活控制执行范围。

编码规范：
    - 严格遵循 PEP 8
    - 使用 Google 风格 docstring
    - 使用 logging 而非 print
    - 使用 pathlib 处理路径
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import yaml

from model_client import chat_with_retry, quick_chat

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量与配置
# ---------------------------------------------------------------------------

DEFAULT_LIMIT = 10
MAX_RETRIES = 3
REQUEST_TIMEOUT = 30.0

_GITHUB_API_URL = "https://api.github.com/search/repositories"

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_RAW_DIR = _PROJECT_ROOT / "knowledge" / "raw"
_ARTICLES_DIR = _PROJECT_ROOT / "knowledge" / "articles"
_RSS_SOURCES_FILE = _PROJECT_ROOT / "pipeline" / "rss_sources.yaml"

# AI 相关关键词，用于过滤和标签提取
_AI_KEYWORDS = [
    "ai", "llm", "agent", "rag", "gpt", "llama", "mistral",
    "openai", "anthropic", "claude", "transformer", "neural",
    "machine learning", "deep learning", "nlp", "cv",
]

# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------


def _ensure_dirs() -> None:
    """确保知识库目录结构存在。"""
    _RAW_DIR.mkdir(parents=True, exist_ok=True)
    _ARTICLES_DIR.mkdir(parents=True, exist_ok=True)


def _now_iso() -> str:
    """返回当前 UTC 时间的 ISO 8601 格式字符串。"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _slugify(text: str) -> str:
    """将文本转换为 URL 友好的 slug。

    Args:
        text: 原始文本。

    Returns:
        str: 小写、连字符分隔的 slug。
    """
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[-\s]+", "-", text)
    return text[:50].strip("-")


def _is_ai_related(text: str) -> bool:
    """判断文本是否与 AI 相关。

    Args:
        text: 待检查的文本。

    Returns:
        bool: 如果包含 AI 关键词则返回 True。
    """
    text_lower = text.lower()
    return any(kw in text_lower for kw in _AI_KEYWORDS)


def _http_get(url: str, headers: dict[str, str] | None = None, params: dict[str, Any] | None = None) -> dict[str, Any] | str:
    """发送 HTTP GET 请求并返回解析后的内容。

    Args:
        url: 请求 URL。
        headers: 可选的请求头。
        params: 可选的查询参数。

    Returns:
        dict | str: JSON 解析后的字典或文本内容。

    Raises:
        RuntimeError: 当请求失败或响应异常时。
    """
    try:
        with httpx.Client(timeout=REQUEST_TIMEOUT) as client:
            response = client.get(url, headers=headers, params=params)
            response.raise_for_status()
            content_type = response.headers.get("content-type", "")
            if "application/json" in content_type:
                return response.json()
            return response.text
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(f"HTTP 错误 {exc.response.status_code}: {url}") from exc
    except httpx.RequestError as exc:
        raise RuntimeError(f"请求失败: {url} - {exc}") from exc


# ---------------------------------------------------------------------------
# Step 1: 采集 (Collect)
# ---------------------------------------------------------------------------


def collect_github(limit: int) -> list[dict[str, Any]]:
    """从 GitHub Search API 采集 AI 相关仓库。

    使用未认证请求（限速 10 req/min）或 GITHUB_TOKEN 认证（30 req/min）。
    按 stars 降序排序，过滤出与 AI 相关的项目。

    Args:
        limit: 最多采集条数。

    Returns:
        list[dict]: 采集到的原始条目列表，每条包含 title, url, raw_content 等字段。
    """
    logger.info("开始采集 GitHub: limit=%d", limit)
    token = os.getenv("GITHUB_TOKEN", "")
    headers = {"Accept": "application/vnd.github.v3+json"}
    if token:
        headers["Authorization"] = f"token {token}"
        logger.debug("使用 GITHUB_TOKEN 认证")

    queries = [
        "llm+language:python",
        "ai+agent+stars:>1000",
        "topic:machine-learning",
        "rag+stars:>500",
    ]

    all_items: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    for query in queries:
        if len(all_items) >= limit:
            break

        params = {
            "q": query,
            "sort": "stars",
            "order": "desc",
            "per_page": min(limit * 2, 30),
        }

        try:
            data = _http_get(_GITHUB_API_URL, headers=headers, params=params)
            if not isinstance(data, dict):
                logger.warning("GitHub API 返回非 JSON 数据")
                continue

            items = data.get("items", [])
            logger.debug("查询 '%s' 返回 %d 条结果", query, len(items))

            for repo in items:
                if len(all_items) >= limit:
                    break

                url = repo.get("html_url", "")
                if url in seen_urls:
                    continue

                name = repo.get("name", "")
                description = repo.get("description") or ""
                full_text = f"{name} {description} {' '.join(repo.get('topics', []))}"

                if not _is_ai_related(full_text):
                    continue

                entry = {
                    "title": name,
                    "url": url,
                    "source": "github_trending",
                    "raw_content": description,
                    "language": repo.get("language"),
                    "stars": repo.get("stargazers_count", 0),
                    "topics": repo.get("topics", []),
                    "collected_at": _now_iso(),
                    "priority": "medium",
                }
                all_items.append(entry)
                seen_urls.add(url)

        except RuntimeError as exc:
            logger.warning("GitHub 查询失败: %s", exc)
            continue

    logger.info("GitHub 采集完成: %d 条", len(all_items))
    return all_items


def _load_rss_sources() -> list[dict[str, Any]]:
    """从 YAML 配置文件加载 RSS 数据源。

    读取 pipeline/rss_sources.yaml，返回所有 enabled=true 的源列表。
    如果配置文件不存在，回退到默认源。

    Returns:
        list[dict]: 启用的 RSS 源配置列表。
    """
    if not _RSS_SOURCES_FILE.exists():
        logger.warning("RSS 配置文件不存在: %s，使用默认源", _RSS_SOURCES_FILE)
        return [
            {"name": "Hacker News", "url": "https://news.ycombinator.com/rss", "category": "general_tech"},
            {"name": "Reddit r/MachineLearning", "url": "https://www.reddit.com/r/MachineLearning/.rss", "category": "general_tech"},
        ]

    try:
        with open(_RSS_SOURCES_FILE, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)

        sources = config.get("rss_sources", [])
        enabled_sources = [s for s in sources if s.get("enabled", False)]

        logger.info("加载 RSS 配置: 总计 %d 个源，启用 %d 个", len(sources), len(enabled_sources))
        for src in enabled_sources:
            logger.debug("  - %s (%s)", src.get("name"), src.get("category"))

        return enabled_sources

    except yaml.YAMLError as exc:
        logger.error("RSS 配置文件解析失败: %s", exc)
        return []


def collect_rss(limit: int) -> list[dict[str, Any]]:
    """从 RSS 源采集 AI 相关内容。

    使用简易正则解析 RSS XML，提取标题、链接和描述。
    从 rss_sources.yaml 读取启用的数据源。

    Args:
        limit: 每条 RSS 源最多采集条数。

    Returns:
        list[dict]: 采集到的原始条目列表。
    """
    logger.info("开始采集 RSS: limit=%d", limit)

    sources = _load_rss_sources()
    if not sources:
        logger.warning("没有启用的 RSS 源，跳过采集")
        return []

    all_items: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    # 提取 <item> 中的 title, link, description
    _ITEM_RE = re.compile(
        r"<item>.*?<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>"
        r".*?<link>(.*?)</link>"
        r"(?:.*?<description>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</description>)?"
        r".*?</item>",
        re.DOTALL | re.IGNORECASE,
    )

    for source in sources:
        feed_url = source.get("url", "")
        source_name = source.get("name", feed_url)
        category = source.get("category", "unknown")
        language = source.get("language", "en")

        if not feed_url:
            logger.warning("RSS 源 '%s' 缺少 URL，跳过", source_name)
            continue

        if len(all_items) >= limit * len(sources):
            break

        try:
            text = _http_get(feed_url)
            if not isinstance(text, str):
                continue

            items = _ITEM_RE.findall(text)
            logger.debug("RSS '%s' 解析出 %d 条", source_name, len(items))

            for title, link, description in items:
                if len(all_items) >= limit * len(sources):
                    break

                title = title.strip()
                link = link.strip()
                description = (description or "").strip()

                # 去除 HTML 标签
                description = re.sub(r"<[^>]+>", "", description)

                if link in seen_urls:
                    continue

                full_text = f"{title} {description}"
                if not _is_ai_related(full_text):
                    continue

                entry = {
                    "title": title,
                    "url": link,
                    "source": f"rss_{category}",
                    "raw_content": description[:500],
                    "language": language,
                    "stars": None,
                    "topics": [],
                    "collected_at": _now_iso(),
                    "priority": "medium",
                }
                all_items.append(entry)
                seen_urls.add(link)

            # 请求间隔，避免对 RSS 服务器造成压力
            time.sleep(1.0)

        except RuntimeError as exc:
            logger.warning("RSS 采集失败 '%s': %s", source_name, exc)
            continue

    logger.info("RSS 采集完成: %d 条", len(all_items))
    return all_items


def save_raw_data(items: list[dict[str, Any]], source: str, dry_run: bool = False) -> Path | None:
    """将采集到的原始数据保存到 knowledge/raw/。

    Args:
        items: 采集到的条目列表。
        source: 数据来源标识（github / rss）。
        dry_run: 是否为干跑模式（不实际写入文件）。

    Returns:
        Path | None: 保存的文件路径，干跑模式返回 None。
    """
    if not items:
        logger.info("无数据需要保存")
        return None

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    filename = f"{source}-{date_str}.json"
    filepath = _RAW_DIR / filename

    # 避免覆盖已存在文件
    counter = 1
    while filepath.exists():
        filename = f"{source}-{date_str}-{counter}.json"
        filepath = _RAW_DIR / filename
        counter += 1

    if dry_run:
        logger.info("[DRY-RUN] 将保存 %d 条到 %s", len(items), filepath)
        return None

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)

    logger.info("原始数据已保存: %s (%d 条)", filepath, len(items))
    return filepath


# ---------------------------------------------------------------------------
# Step 2: 分析 (Analyze)
# ---------------------------------------------------------------------------


_ANALYSIS_SYSTEM_PROMPT = """你是一位专业的 AI 技术分析师。你的任务是对给定的技术内容进行分析，输出严格的 JSON 格式。

请分析以下内容，提取：
1. summary: 200-500 字的中文摘要，说明这是什么、为什么值得关注
2. tags: 1-5 个技术标签（如 ["LLM", "Agent", "RAG"]）
3. tech_category: 技术分类，必须是以下之一：model | infra | tool | application | research
4. audience: 目标受众，必须是以下之一：researcher | developer | product | general
5. score: 质量评分（1-10 分，基于技术影响力、创新性、实用性）
6. key_insights: 2-4 条核心观点（字符串数组）

输出必须是合法的 JSON，不要包含任何 markdown 标记或其他解释文字：
{
  "summary": "...",
  "tags": ["tag1", "tag2"],
  "tech_category": "tool",
  "audience": "developer",
  "score": 8,
  "key_insights": [" insight 1", "insight 2"]
}"""


def analyze_item(item: dict[str, Any]) -> dict[str, Any] | None:
    """调用 LLM 对单条内容进行深度分析。

    Args:
        item: 采集到的原始条目，至少包含 title 和 raw_content。

    Returns:
        dict | None: 分析结果字典，失败时返回 None。
    """
    title = item.get("title", "")
    content = item.get("raw_content", "")
    url = item.get("url", "")

    if not content:
        content = title

    prompt = f"标题: {title}\n链接: {url}\n内容: {content[:2000]}"

    try:
        response = quick_chat(
            prompt=prompt,
            system_prompt=_ANALYSIS_SYSTEM_PROMPT,
            temperature=0.3,
            max_tokens=1500,
        )

        # 清理可能的 markdown 代码块
        cleaned = re.sub(r"```json\s*|\s*```", "", response).strip()
        analysis = json.loads(cleaned)

        # 基础校验
        required_keys = {"summary", "tags", "tech_category", "audience", "score", "key_insights"}
        if not required_keys.issubset(analysis.keys()):
            logger.warning("LLM 分析结果缺少必要字段: %s", analysis.keys())
            return None

        # 校验 tech_category 和 audience 枚举值
        valid_categories = {"model", "infra", "tool", "application", "research"}
        valid_audiences = {"researcher", "developer", "product", "general"}

        if analysis["tech_category"] not in valid_categories:
            analysis["tech_category"] = "application"
        if analysis["audience"] not in valid_audiences:
            analysis["audience"] = "developer"

        # 确保 score 为整数
        try:
            analysis["score"] = int(analysis["score"])
            analysis["score"] = max(1, min(10, analysis["score"]))
        except (ValueError, TypeError):
            analysis["score"] = 5

        # 确保 tags 为列表
        if not isinstance(analysis["tags"], list):
            analysis["tags"] = [str(analysis["tags"])]
        analysis["tags"] = [str(t) for t in analysis["tags"]][:5]

        # 确保 key_insights 为列表
        if not isinstance(analysis["key_insights"], list):
            analysis["key_insights"] = [str(analysis["key_insights"])]
        analysis["key_insights"] = [str(k)[:200] for k in analysis["key_insights"]][:4]

        logger.info("分析完成: title=%s, score=%d", title[:40], analysis["score"])
        return analysis

    except json.JSONDecodeError as exc:
        logger.warning("LLM 输出 JSON 解析失败 '%s': %s", title[:40], exc)
    except Exception as exc:
        logger.warning("LLM 分析失败 '%s': %s", title[:40], exc)

    return None


# ---------------------------------------------------------------------------
# Step 3: 整理 (Organize)
# ---------------------------------------------------------------------------


def deduplicate(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """基于 URL 去重。

    Args:
        items: 待去重的条目列表。

    Returns:
        list[dict]: 去重后的条目列表。
    """
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []

    for item in items:
        url = item.get("url", "")
        if url and url in seen:
            logger.debug("去重丢弃: %s", url)
            continue
        seen.add(url)
        unique.append(item)

    logger.info("去重完成: %d -> %d", len(items), len(unique))
    return unique


def standardize(item: dict[str, Any], analysis: dict[str, Any] | None, seq_num: int = 0) -> dict[str, Any]:
    """将原始条目和分析结果合并为标准化的知识条目格式。

    Args:
        item: 原始采集条目。
        analysis: LLM 分析结果，可能为 None。
        seq_num: 当天同源的递增序号，用于生成 ID。

    Returns:
        dict: 符合知识库 Schema 的标准化条目。
    """
    now = _now_iso()
    title = item.get("title", "未命名")

    # 生成 ID: {source}-{YYYYMMDD}-{NNN}
    date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    source_platform = item.get("source", "unknown")
    entry_id = f"{source_platform.replace('_', '-')}-{date_str}-{seq_num:03d}"

    # 构建 metrics
    metrics: dict[str, Any] = {}
    if item.get("stars") is not None:
        metrics["stars"] = item["stars"]

    # 构建 ai_analysis
    ai_analysis: dict[str, Any] = {
        "key_insights": analysis.get("key_insights", []) if analysis else [],
        "tech_category": analysis.get("tech_category", "application") if analysis else "application",
        "audience": analysis.get("audience", "developer") if analysis else "developer",
    }

    standardized = {
        "id": entry_id,
        "title": title,
        "source_url": item.get("url", ""),
        "source_platform": source_platform,
        "summary": (analysis.get("summary", "") if analysis else item.get("raw_content", ""))[:500],
        "tags": analysis.get("tags", []) if analysis else [],
        "author": None,
        "published_at": item.get("collected_at", now),
        "collected_at": now,
        "status": "draft",
        "priority": item.get("priority", "medium"),
        "language": item.get("language"),
        "retry_count": 0,
        "metrics": metrics,
        "ai_analysis": ai_analysis,
        "version": 1,
    }

    return standardized


def validate(entry: dict[str, Any]) -> tuple[bool, str]:
    """校验知识条目是否符合基本规范。

    Args:
        entry: 待校验的知识条目。

    Returns:
        tuple[bool, str]: (是否通过, 错误信息)。
    """
    required_fields = ["id", "title", "source_url", "source_platform", "summary", "status"]
    for field in required_fields:
        if not entry.get(field):
            return False, f"缺少必填字段: {field}"

    if len(entry.get("summary", "")) < 10:
        return False, "摘要过短（< 10 字符）"

    valid_statuses = {"draft", "review", "published", "archived"}
    if entry["status"] not in valid_statuses:
        return False, f"无效状态: {entry['status']}"

    return True, ""


# ---------------------------------------------------------------------------
# Step 4: 保存 (Save)
# ---------------------------------------------------------------------------


def save_article(entry: dict[str, Any], dry_run: bool = False) -> Path | None:
    """将单条知识条目保存为独立 JSON 文件。

    文件名格式: {source_platform}_{date}_{slug}.json

    Args:
        entry: 标准化的知识条目。
        dry_run: 是否为干跑模式。

    Returns:
        Path | None: 保存的文件路径，干跑模式返回 None。
    """
    source = entry.get("source_platform", "unknown")
    date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    slug = _slugify(entry.get("title", "untitled"))
    filename = f"{source}_{date_str}_{slug}.json"
    filepath = _ARTICLES_DIR / filename

    # 避免覆盖
    counter = 1
    original_filepath = filepath
    while filepath.exists():
        filename = f"{source}_{date_str}_{slug}_{counter}.json"
        filepath = _ARTICLES_DIR / filename
        counter += 1

    if dry_run:
        logger.info("[DRY-RUN] 将保存文章: %s", filepath.name)
        return None

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(entry, f, ensure_ascii=False, indent=2)

    logger.info("文章已保存: %s", filepath.name)
    return filepath


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


def run_pipeline(sources: list[str], limit: int, dry_run: bool = False) -> dict[str, Any]:
    """执行完整的四步流水线。

    Args:
        sources: 数据源列表，如 ["github", "rss"]。
        limit: 每个源最多采集条数。
        dry_run: 是否为干跑模式。

    Returns:
        dict: 执行统计信息。
    """
    _ensure_dirs()
    stats = {"collected": 0, "analyzed": 0, "saved": 0, "failed": 0, "errors": []}

    # ---- Step 1: 采集 ----
    all_raw: list[dict[str, Any]] = []

    for source in sources:
        source = source.strip().lower()
        if source == "github":
            items = collect_github(limit)
        elif source == "rss":
            items = collect_rss(limit)
        else:
            logger.warning("未知数据源: %s", source)
            continue

        if items:
            save_raw_data(items, source, dry_run=dry_run)
            all_raw.extend(items)

    stats["collected"] = len(all_raw)
    logger.info("采集总计: %d 条", stats["collected"])

    if not all_raw:
        logger.info("无数据需要处理，流水线结束")
        return stats

    # ---- Step 3 (前置): 去重 ----
    unique_items = deduplicate(all_raw)

    # ---- Step 2: 分析 + Step 3: 整理 ----
    source_counters: dict[str, int] = defaultdict(int)
    for item in unique_items:
        analysis = analyze_item(item)
        if analysis:
            stats["analyzed"] += 1

        source = item.get("source", "unknown")
        source_counters[source] += 1
        entry = standardize(item, analysis, seq_num=source_counters[source])

        # 校验
        valid, error_msg = validate(entry)
        if not valid:
            logger.warning("校验失败 '%s': %s", entry.get("title", ""), error_msg)
            stats["failed"] += 1
            stats["errors"].append({"title": entry.get("title"), "error": error_msg})
            continue

        # ---- Step 4: 保存 ----
        saved_path = save_article(entry, dry_run=dry_run)
        if saved_path or dry_run:
            stats["saved"] += 1

    logger.info(
        "流水线完成: collected=%d, analyzed=%d, saved=%d, failed=%d",
        stats["collected"],
        stats["analyzed"],
        stats["saved"],
        stats["failed"],
    )
    return stats


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    """CLI 入口。

    Returns:
        int: 退出码，0 表示成功。
    """
    parser = argparse.ArgumentParser(
        description="AI 知识库自动化流水线 — 采集、分析、整理、保存",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python pipeline/pipeline.py --sources github,rss --limit 20
  python pipeline/pipeline.py --sources github --limit 5 --dry-run
  python pipeline/pipeline.py --sources rss --limit 10 --verbose
        """,
    )
    parser.add_argument(
        "--sources",
        type=str,
        default="github,rss",
        help="数据源，逗号分隔。可选: github, rss (默认: github,rss)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help=f"每个源最多采集条数 (默认: {DEFAULT_LIMIT})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="干跑模式：执行所有步骤但不写入文件",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="启用详细日志 (DEBUG 级别)",
    )

    args = parser.parse_args()

    # 配置日志
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    sources = [s.strip() for s in args.sources.split(",") if s.strip()]
    if not sources:
        logger.error("至少指定一个数据源")
        return 1

    logger.info("=" * 50)
    logger.info("启动流水线: sources=%s, limit=%d, dry_run=%s", sources, args.limit, args.dry_run)
    logger.info("=" * 50)

    try:
        stats = run_pipeline(sources=sources, limit=args.limit, dry_run=args.dry_run)

        logger.info("=" * 50)
        logger.info("流水线执行统计:")
        logger.info("  采集: %d 条", stats["collected"])
        logger.info("  分析: %d 条", stats["analyzed"])
        logger.info("  保存: %d 条", stats["saved"])
        logger.info("  失败: %d 条", stats["failed"])
        if stats["errors"]:
            logger.info("  错误详情:")
            for err in stats["errors"]:
                logger.info("    - %s: %s", err["title"], err["error"])
        logger.info("=" * 50)

        return 0 if stats["failed"] == 0 else 1

    except KeyboardInterrupt:
        logger.info("用户中断执行")
        return 130
    except Exception as exc:
        logger.exception("流水线执行失败: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
