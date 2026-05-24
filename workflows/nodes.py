"""LangGraph 工作流节点函数定义。

实现知识库采集工作流的 5 个节点：
    - collect_node: 采集 AI 相关仓库数据
    - analyze_node: LLM 分析生成摘要、标签、评分
    - organize_node: 过滤低分、去重、定向修正
    - review_node: 四维度质量审核
    - save_node: 写入 JSON 并更新索引

每个节点是纯函数：接收 KBState，返回 dict（部分状态更新）。

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
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from pipeline.model_client import Usage
from workflows.model_client import chat, chat_json
from workflows.state import KBState

logger = logging.getLogger(__name__)

# ── GitHub Search API 常量 ──────────────────────────────────
_GITHUB_SEARCH_API = "https://api.github.com/search/repositories"
_GITHUB_QUERY = "stars:>1000 AI OR LLM OR agent OR transformer"

# ── 知识库目录 ──────────────────────────────────────────────
_KNOWLEDGE_DIR = _PROJECT_ROOT / "knowledge" / "articles"


def accumulate_usage(
    tracker: dict[str, Any],
    usage: Usage,
    node_name: str = "unknown",
) -> dict[str, Any]:
    """累加 LLM 调用 Token 用量到 cost_tracker。

    Args:
        tracker: cost_tracker 字典。
        usage: 本次调用的 Usage 对象。
        node_name: 调用来源节点名称，用于统计各节点调用次数。

    Returns:
        dict[str, Any]: 更新后的 tracker 字典。
    """
    tracker["total_prompt_tokens"] += usage.prompt_tokens
    tracker["total_completion_tokens"] += usage.completion_tokens
    tracker["total_tokens"] += usage.total_tokens

    calls = tracker.setdefault("calls_by_node", {})
    calls[node_name] = calls.get(node_name, 0) + 1

    logger.info(
        "[%s] Token 累加: +prompt=%d, +completion=%d, 总计=%d",
        node_name,
        usage.prompt_tokens,
        usage.completion_tokens,
        tracker["total_tokens"],
    )
    return tracker


# ═══════════════════════════════════════════════════════════════
#  1. collect_node
# ═══════════════════════════════════════════════════════════════

def collect_node(state: KBState) -> dict[str, Any]:
    """采集节点：调用 GitHub Search API 搜索 AI 相关热门仓库。

    搜索条件：star > 1000，关键词包含 AI / LLM / agent / transformer，
    按 star 数降序排列，取前 10 条。

    Args:
        state: 当前工作流状态。

    Returns:
        dict[str, Any]: 包含更新后的 sources 列表和 cost_tracker。
    """
    logger.info("[collect_node] 开始采集 GitHub 仓库...")

    encoded_query = urllib.parse.quote(_GITHUB_QUERY)
    url = (
        f"{_GITHUB_SEARCH_API}?q={encoded_query}"
        f"&sort=stars&order=desc&per_page=10"
    )

    try:
        req = urllib.request.Request(
            url,
            headers={
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": "KB-Workflow/1.0",
            },
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        logger.error("[collect_node] GitHub API HTTP %d: %s", exc.code, exc.reason)
        return {"sources": [], "cost_tracker": state.get("cost_tracker", {})}
    except Exception as exc:
        logger.error("[collect_node] 采集异常: %s", exc)
        return {"sources": [], "cost_tracker": state.get("cost_tracker", {})}

    items = data.get("items", [])
    sources: list[dict[str, Any]] = []

    for item in items:
        sources.append({
            "platform": "github_trending",
            "raw_url": item.get("html_url", ""),
            "title": item.get("full_name", "未知仓库"),
            "description": item.get("description", ""),
            "stars": item.get("stargazers_count", 0),
            "language": item.get("language", "Unknown"),
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "metadata": {
                "forks": item.get("forks_count", 0),
                "topics": item.get("topics", []),
            },
        })

    logger.info("[collect_node] 采集完成: %d 条仓库数据", len(sources))
    return {"sources": sources, "cost_tracker": state.get("cost_tracker", {})}


# ═══════════════════════════════════════════════════════════════
#  2. analyze_node
# ═══════════════════════════════════════════════════════════════

_ANALYZE_SYSTEM_PROMPT = (
    "你是一个技术资讯分析专家。请根据给定的 GitHub 仓库信息，"
    "生成一份结构化的中文分析报告。\n\n"
    "输出必须严格符合以下 JSON 格式（不要包含 markdown 代码块）：\n"
    '{"summary": "200-500字的中文摘要", '
    '"tags": ["标签1", "标签2", "标签3"], '
    '"category": "tool/framework/paper/library 之一", '
    '"score": 0.85}'
    "\n\n评分标准（score: 0.0-1.0）：\n"
    "- 0.8-1.0: 高影响力、与 AI/LLM 强相关、社区活跃\n"
    "- 0.6-0.8: 有一定相关性，但影响力一般\n"
    "- 0.4-0.6: 弱相关，参考价值有限\n"
    "- 0.0-0.4: 不相关或质量低下"
)


def analyze_node(state: KBState) -> dict[str, Any]:
    """分析节点：用 LLM 对每条 source 生成中文摘要、标签、评分。

    遍历 sources 列表，对每条数据调用 LLM 生成结构化分析结果。
    Token 用量通过 accumulate_usage 累加到 cost_tracker。

    Args:
        state: 当前工作流状态，必须包含 sources 字段。

    Returns:
        dict[str, Any]: 包含更新后的 analyses 列表和 cost_tracker。
    """
    logger.info("[analyze_node] 开始分析 %d 条数据...", len(state.get("sources", [])))

    sources = state.get("sources", [])
    tracker = state.get("cost_tracker", {}).copy()
    analyses: list[dict[str, Any]] = []

    for idx, src in enumerate(sources):
        prompt = (
            f"仓库名称: {src['title']}\n"
            f"描述: {src.get('description', '无描述')}\n"
            f"编程语言: {src.get('language', 'Unknown')}\n"
            f"Stars: {src.get('stars', 0)}\n"
            f"Topics: {', '.join(src.get('metadata', {}).get('topics', []))}\n\n"
            "请生成中文分析报告。"
        )

        try:
            parsed, usage = chat_json(
                prompt=prompt,
                system_prompt=_ANALYZE_SYSTEM_PROMPT,
                temperature=0.7,
            )
            accumulate_usage(tracker, usage, node_name="analyze_node")

            analyses.append({
                "source_index": idx,
                "summary": parsed.get("summary", ""),
                "tags": parsed.get("tags", []),
                "category": parsed.get("category", "unknown"),
                "score": float(parsed.get("score", 0.5)),
                "analyzed_at": datetime.now(timezone.utc).isoformat(),
            })
            logger.info(
                "[analyze_node] 分析完成 [%d/%d]: %s, score=%.2f",
                idx + 1,
                len(sources),
                src["title"],
                float(parsed.get("score", 0.5)),
            )
        except Exception as exc:
            logger.error("[analyze_node] 分析失败 [%d]: %s - %s", idx, src["title"], exc)
            analyses.append({
                "source_index": idx,
                "summary": f"分析失败: {exc}",
                "tags": [],
                "category": "unknown",
                "score": 0.0,
                "analyzed_at": datetime.now(timezone.utc).isoformat(),
            })

    logger.info("[analyze_node] 分析完成: %d/%d 成功", len(analyses), len(sources))
    return {"analyses": analyses, "cost_tracker": tracker}


# ═══════════════════════════════════════════════════════════════
#  3. organize_node
# ═══════════════════════════════════════════════════════════════

_ORGANIZE_SYSTEM_PROMPT = (
    "你是一个技术资讯编辑。请根据给定的审核反馈，"
    "对知识条目进行定向修改。\n\n"
    "输出必须严格符合以下 JSON 格式：\n"
    '{"summary": "修改后的中文摘要", '
    '"tags": ["标签1", "标签2"], '
    '"category": "tool/framework/paper/library 之一"}'
)


def organize_node(state: KBState) -> dict[str, Any]:
    """组织节点：过滤低分、去重、定向修正。

    处理流程：
        1. 过滤 analyses 中 score < 0.6 的低分条目
        2. 按 URL 去重（保留 score 最高的一条）
        3. 如果 iteration > 0 且有 review_feedback，调用 LLM 定向修正
        4. 组装为标准的 article 格式

    Args:
        state: 当前工作流状态，必须包含 sources、analyses、
               review_feedback、iteration 字段。

    Returns:
        dict[str, Any]: 包含更新后的 articles 列表和 cost_tracker。
    """
    logger.info("[organize_node] 开始组织数据...")

    sources = state.get("sources", [])
    analyses = state.get("analyses", [])
    feedback = state.get("review_feedback", "")
    iteration = state.get("iteration", 0)
    tracker = state.get("cost_tracker", {}).copy()

    # 1. 过滤低分
    filtered = [a for a in analyses if a.get("score", 0) >= 0.6]
    logger.info("[organize_node] 过滤低分: %d -> %d", len(analyses), len(filtered))

    # 2. 按 URL 去重（保留 score 最高）
    seen_urls: dict[str, dict[str, Any]] = {}
    for ana in filtered:
        idx = ana.get("source_index", -1)
        if idx < 0 or idx >= len(sources):
            continue
        url = sources[idx].get("raw_url", "")
        if not url:
            continue
        if url not in seen_urls or ana.get("score", 0) > seen_urls[url].get("score", 0):
            seen_urls[url] = ana

    logger.info("[organize_node] URL 去重: %d -> %d", len(filtered), len(seen_urls))

    # 3. 定向修正（iteration > 0 且有 feedback）
    corrected = []
    for url, ana in seen_urls.items():
        if iteration > 0 and feedback:
            try:
                prompt = (
                    f"原始摘要: {ana['summary']}\n"
                    f"原始标签: {', '.join(ana['tags'])}\n"
                    f"原始分类: {ana['category']}\n\n"
                    f"审核反馈: {feedback}\n\n"
                    "请根据反馈进行定向修改。"
                )
                text, usage = chat(
                    prompt=prompt,
                    system_prompt=_ORGANIZE_SYSTEM_PROMPT,
                    temperature=0.5,
                )
                accumulate_usage(tracker, usage, node_name="organize_node")

                parsed = json.loads(text.strip().lstrip("`").rstrip("`").replace("json", "", 1).strip()) if text.strip().startswith("```") else json.loads(text)

                ana = ana.copy()
                ana["summary"] = parsed.get("summary", ana["summary"])
                ana["tags"] = parsed.get("tags", ana["tags"])
                ana["category"] = parsed.get("category", ana["category"])
                logger.info("[organize_node] 定向修正: %s", url)
            except Exception as exc:
                logger.warning("[organize_node] 修正失败: %s", exc)
        corrected.append(ana)

    # 4. 组装 article 格式
    articles: list[dict[str, Any]] = []
    date_str = datetime.now(timezone.utc).strftime("%Y%m%d")

    for ana in corrected:
        idx = ana.get("source_index", -1)
        src = sources[idx] if 0 <= idx < len(sources) else {}
        article_id = f"github_trending_{date_str}_{src.get('title', 'unknown').replace('/', '_')}"

        articles.append({
            "id": article_id,
            "title": src.get("title", "无标题"),
            "source_url": src.get("raw_url", ""),
            "source_platform": src.get("platform", "github_trending"),
            "summary": ana.get("summary", ""),
            "tags": ana.get("tags", []),
            "category": ana.get("category", "unknown"),
            "score": ana.get("score", 0.0),
            "language": src.get("language", "Unknown"),
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "status": "draft",
        })

    logger.info("[organize_node] 组织完成: %d 条 article", len(articles))
    return {"articles": articles, "cost_tracker": tracker}


# ═══════════════════════════════════════════════════════════════
#  4. review_node
# ═══════════════════════════════════════════════════════════════

_REVIEW_SYSTEM_PROMPT = (
    "你是一个严格的质量审核员。请对给定的知识条目进行四维度评分。\n\n"
    "评分维度（每项 0.0-1.0）：\n"
    "- summary_quality: 摘要质量（是否准确、完整、中文通顺）\n"
    "- tag_accuracy: 标签准确性（标签是否恰当反映内容）\n"
    "- category_reasonableness: 分类合理性（分类是否符合实际）\n"
    "- consistency: 一致性（标题、摘要、标签、分类之间是否一致）\n\n"
    "综合得分 overall_score 为四项平均值。\n"
    "通过标准：overall_score >= 0.7。\n\n"
    "输出必须严格符合以下 JSON 格式（不要包含 markdown 代码块）：\n"
    '{"passed": true/false, '
    '"overall_score": 0.85, '
    '"feedback": "具体的改进建议，已通过可写65e0"'
    '"scores": {"summary_quality": 0.8, "tag_accuracy": 0.9, '
    '"category_reasonableness": 0.85, "consistency": 0.9}}'
)


def review_node(state: KBState) -> dict[str, Any]:
    """审核节点：对 articles 进行四维度质量评分。

    如果 iteration >= 2，强制通过（避免无限循环）。
    否则调用 LLM 进行四维度评分。

    Args:
        state: 当前工作流状态，必须包含 articles、iteration 字段。

    Returns:
        dict[str, Any]: 包含 review_passed、review_feedback、
                        iteration 和 cost_tracker。
    """
    iteration = state.get("iteration", 0)
    logger.info("[review_node] 开始审核 (iteration=%d)...", iteration)

    articles = state.get("articles", [])
    tracker = state.get("cost_tracker", {}).copy()

    # 强制通过：iteration >= 2
    if iteration >= 2:
        logger.info("[review_node] iteration=%d >= 2，强制通过", iteration)
        return {
            "review_passed": True,
            "review_feedback": "已达到最大迭代次数，强制通过。",
            "iteration": iteration,
            "cost_tracker": tracker,
        }

    if not articles:
        logger.warning("[review_node] articles 为空，直接通过")
        return {
            "review_passed": True,
            "review_feedback": "无内容可审核。",
            "iteration": iteration,
            "cost_tracker": tracker,
        }

    # 构建审核输入（最多 review 前 5 条，避免 prompt 过长）
    review_input = []
    for idx, art in enumerate(articles[:5]):
        review_input.append({
            "index": idx,
            "title": art.get("title", ""),
            "summary": art.get("summary", "")[:100],
            "tags": art.get("tags", []),
            "category": art.get("category", ""),
            "score": art.get("score", 0.0),
        })

    prompt = (
        "请对以下知识条目进行质量审核：\n\n"
        f"{json.dumps(review_input, ensure_ascii=False, indent=2)}\n\n"
        "请返回 JSON 格式的审核结果。"
    )

    try:
        text, usage = chat(
            prompt=prompt,
            system_prompt=_REVIEW_SYSTEM_PROMPT,
            temperature=0.3,
        )
        accumulate_usage(tracker, usage, node_name="review_node")

        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3].strip()

        result = json.loads(cleaned)
        passed = result.get("passed", False)
        overall_score = float(result.get("overall_score", 0.0))
        feedback = result.get("feedback", "")

        logger.info(
            "[review_node] 审核结果: passed=%s, overall_score=%.2f",
            passed,
            overall_score,
        )

        return {
            "review_passed": passed,
            "review_feedback": feedback,
            "iteration": iteration + 1,
            "cost_tracker": tracker,
        }
    except Exception as exc:
        logger.error("[review_node] 审核异常: %s", exc)
        return {
            "review_passed": False,
            "review_feedback": f"审核异常: {exc}",
            "iteration": iteration + 1,
            "cost_tracker": tracker,
        }


def review_node_test(state: KBState) -> dict[str, Any]:
    """审核节点：测试版本（前2次不通过，第3次通过）。

    用于验证审核循环：organize → review → organize → review → save
    在 graph.py 中通过注释切换使用。

    Args:
        state: 当前工作流状态，必须包含 articles、iteration 字段。

    Returns:
        dict[str, Any]: 包含 review_passed、review_feedback、
                        iteration 和 cost_tracker。
    """
    iteration = state.get("iteration", 0)
    logger.info("[review_node_test] 开始审核 (iteration=%d)...", iteration)

    articles = state.get("articles", [])
    tracker = state.get("cost_tracker", {}).copy()

    # 测试逻辑：前 2 次不通过，第 3 次通过
    if iteration == 0:
        passed = False
        feedback = (
            "测试反馈（第1轮）：摘要不够深入，标签缺少关键技术点，"
            "请补充 RAG、Agent 等技术标签并重写摘要。"
        )
    elif iteration == 1:
        passed = False
        feedback = (
            "测试反馈（第2轮）：分类不够准确，部分条目应归类为 framework "
            "而非 tool，请重新评估技术领域。"
        )
    else:
        passed = True
        feedback = "测试反馈（第3轮）：已达到最大迭代次数，强制通过。"

    # 打印当前状态
    print(f"  [review_node_test] iteration={iteration}, review_passed={passed}")

    logger.info(
        "[review_node_test] 审核结果: passed=%s, feedback=%s...",
        passed,
        feedback[:50],
    )

    if not articles:
        logger.warning("[review_node_test] articles 为空，直接通过")
        return {
            "review_passed": True,
            "review_feedback": "无内容可审核。",
            "iteration": iteration,
            "cost_tracker": tracker,
        }

    return {
        "review_passed": passed,
        "review_feedback": feedback,
        "iteration": iteration + 1,
        "cost_tracker": tracker,
    }



# ═══════════════════════════════════════════════════════════════
#  5. save_node
# ═══════════════════════════════════════════════════════════════

def save_node(state: KBState) -> dict[str, Any]:
    """保存节点：将 articles 写入 JSON 文件并更新索引。

    写入路径：knowledge/articles/<id>.json
    同时更新或创建 knowledge/articles/index.json 索引文件。

    Args:
        state: 当前工作流状态，必须包含 articles 字段。

    Returns:
        dict[str, Any]: 包含 cost_tracker（无额外修改）。
    """
    logger.info("[save_node] 开始保存数据...")

    articles = state.get("articles", [])
    tracker = state.get("cost_tracker", {}).copy()

    if not articles:
        logger.warning("[save_node] articles 为空，无数据可保存")
        return {"cost_tracker": tracker}

    _KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)

    # 写入每条 article 为独立 JSON 文件
    saved_count = 0
    for art in articles:
        file_id = art.get("id", str(uuid.uuid4()))
        file_path = _KNOWLEDGE_DIR / f"{file_id}.json"

        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(art, f, ensure_ascii=False, indent=2)
            saved_count += 1
            logger.info("[save_node] 已保存: %s", file_path.name)
        except OSError as exc:
            logger.error("[save_node] 保存失败: %s - %s", file_path, exc)

    # 更新 index.json 索引
    _update_index(articles)

    logger.info("[save_node] 保存完成: %d/%d 条", saved_count, len(articles))
    return {"cost_tracker": tracker}


def _update_index(articles: list[dict[str, Any]]) -> None:
    """更新 knowledge/articles/index.json 索引文件。

    索引包含所有 article 的元数据（不含完整摘要），
    用于快速检索和列表展示。

    Args:
        articles: 当前批次要索引的文章列表。
    """
    index_path = _KNOWLEDGE_DIR / "index.json"

    # 读取现有索引
    existing: list[dict[str, Any]] = []
    if index_path.exists():
        try:
            with open(index_path, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("[save_node] 读取现有索引失败: %s", exc)

    # 构建新索引条目
    existing_ids = {entry.get("id") for entry in existing}
    new_entries = []

    for art in articles:
        art_id = art.get("id")
        if art_id and art_id not in existing_ids:
            new_entries.append({
                "id": art_id,
                "title": art.get("title", ""),
                "source_url": art.get("source_url", ""),
                "source_platform": art.get("source_platform", ""),
                "tags": art.get("tags", []),
                "category": art.get("category", ""),
                "score": art.get("score", 0.0),
                "language": art.get("language", ""),
                "collected_at": art.get("collected_at", ""),
                "status": art.get("status", "draft"),
            })

    # 合并并写入
    combined = existing + new_entries
    try:
        with open(index_path, "w", encoding="utf-8") as f:
            json.dump(combined, f, ensure_ascii=False, indent=2)
        logger.info(
            "[save_node] 索引更新: +%d 条, 总计 %d 条",
            len(new_entries),
            len(combined),
        )
    except OSError as exc:
        logger.error("[save_node] 索引写入失败: %s", exc)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    print("=" * 60)
    print("Nodes 节点函数测试")
    print("=" * 60)

    # 测试 accumulate_usage
    tracker = {
        "total_prompt_tokens": 0,
        "total_completion_tokens": 0,
        "total_tokens": 0,
        "total_cost_usd": 0.0,
        "calls_by_node": {},
    }
    u = Usage(prompt_tokens=100, completion_tokens=50, total_tokens=150)
    accumulate_usage(tracker, u, "test_node")
    print(f"\naccumulate_usage 测试: {tracker}")

    # 测试 init_state -> collect -> organize 链
    from workflows.state import init_state

    state = init_state()
    print(f"\n初始状态: {len(state['sources'])} sources")

    # 手动设置一些测试数据
    state["sources"] = [
        {
            "platform": "github_trending",
            "raw_url": "https://github.com/test/repo1",
            "title": "test/repo1",
            "description": "A test repository for AI",
            "stars": 5000,
            "language": "Python",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "metadata": {"forks": 100, "topics": ["ai", "llm"]},
        },
        {
            "platform": "github_trending",
            "raw_url": "https://github.com/test/repo2",
            "title": "test/repo2",
            "description": "Another test repo",
            "stars": 2000,
            "language": "TypeScript",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "metadata": {"forks": 50, "topics": ["agent"]},
        },
    ]

    state["analyses"] = [
        {
            "source_index": 0,
            "summary": "这是一个测试仓库，用于演示 AI 功能。",
            "tags": ["AI", "Python"],
            "category": "tool",
            "score": 0.85,
            "analyzed_at": datetime.now(timezone.utc).isoformat(),
        },
        {
            "source_index": 1,
            "summary": "另一个测试仓库，用于 Agent 开发。",
            "tags": ["Agent", "TypeScript"],
            "category": "framework",
            "score": 0.55,
            "analyzed_at": datetime.now(timezone.utc).isoformat(),
        },
    ]

    print("\n--- 测试 organize_node ---")
    result = organize_node(state)
    print(f"articles: {len(result['articles'])} 条")
    for art in result["articles"]:
        print(f"  - {art['title']}: score={art['score']}, category={art['category']}")

    print("\n--- 测试 review_node (iteration=0) ---")
    state["articles"] = result["articles"]
    state["cost_tracker"] = result["cost_tracker"]
    review_result = review_node(state)
    print(f"review_passed: {review_result['review_passed']}")
    print(f"review_feedback: {review_result['review_feedback'][:100]}...")
    print(f"iteration: {review_result['iteration']}")

    print("\n--- 测试 save_node ---")
    state["articles"] = result["articles"]
    state["cost_tracker"] = review_result["cost_tracker"]
    save_result = save_node(state)
    print(f"cost_tracker: {save_result['cost_tracker']}")

    print(f"\n{'=' * 60}")
    print("测试结束")
    print("=" * 60)
