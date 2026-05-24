"""Reviser 修正模块：根据审核反馈修改 analyses。

实现 revise_node 函数，将 reviewer 的反馈意见注入 LLM prompt，
生成改进后的 analyses 列表，供 organize 节点重新处理。

编码规范：
    - 严格遵循 PEP 8
    - 使用 Google 风格 docstring
    - 使用 logging 而非 print
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from workflows.model_client import chat_json
from workflows.nodes import accumulate_usage
from workflows.state import KBState

logger = logging.getLogger(__name__)

# ── System Prompt ───────────────────────────────────────────
_REVISE_SYSTEM_PROMPT = (
    "你是一个资深技术编辑。请根据给定的审核反馈意见，"
    "对 analyses 列表中的每条数据进行定向修改。\n\n"
    "修改要求：\n"
    "1. 针对 feedback 中提到的问题逐条修正\n"
    "2. 保持原有字段结构不变（source_index, summary, tags, category, score）\n"
    "3. summary 用中文重写，200-500 字\n"
    "4. tags 保留最相关的 3-7 个技术标签\n"
    "5. category 从 tool/framework/paper/library 中选择最准确的一个\n"
    "6. score 根据改进后的质量重新评估（0.0-1.0）\n\n"
    "输出 JSON 格式（不要 markdown 代码块）：\n"
    '{"analyses": [{"source_index": 0, "summary": "...", '
    '"tags": ["..."], "category": "...", "score": 0.85}, ...]}'
)


def revise_node(state: KBState) -> dict[str, Any]:
    """修正节点：根据 review_feedback 修改 analyses。

    读取 state["analyses"] 和 state["review_feedback"]，
    将 feedback 注入 LLM prompt，生成改进后的 analyses 列表。

    Args:
        state: 当前工作流状态，必须包含 analyses、review_feedback、
               cost_tracker 字段。

    Returns:
        dict[str, Any]: {"analyses": improved_list, "cost_tracker": tracker}。
        如果 analyses 或 feedback 为空，返回空字典 {}。
    """
    analyses = state.get("analyses", [])
    feedback = state.get("review_feedback", "")
    tracker = state.get("cost_tracker", {}).copy()

    logger.info("[reviser] 开始修正 analyses (total=%d)...", len(analyses))

    # 跳过条件：analyses 或 feedback 为空
    if not analyses:
        logger.info("[reviser] analyses 为空，跳过修正")
        return {}

    if not feedback or not feedback.strip():
        logger.info("[reviser] review_feedback 为空，跳过修正")
        return {}

    # 构建修改输入（只保留关键字段，减少 token）
    revise_input = []
    for ana in analyses[:10]:  # 最多修正前 10 条
        revise_input.append({
            "source_index": ana.get("source_index", -1),
            "summary": ana.get("summary", "")[:200],
            "tags": ana.get("tags", []),
            "category": ana.get("category", ""),
            "score": ana.get("score", 0.0),
        })

    prompt = (
        f"审核反馈意见：\n{feedback.strip()}\n\n"
        f"需要修改的 analyses 列表：\n"
        f"{json.dumps(revise_input, ensure_ascii=False, indent=2)}\n\n"
        "请根据反馈意见逐条修改，返回完整的改进后 analyses 列表。"
    )

    try:
        result, usage = chat_json(
            node_name="reviser",
            prompt=prompt,
            system_prompt=_REVISE_SYSTEM_PROMPT,
            temperature=0.4,
        )
        accumulate_usage(tracker, usage, node_name="reviser")

        if "error" in result:
            logger.warning("[reviser] LLM 返回错误: %s", result.get("error"))
            return {}

        improved = result.get("analyses", [])
        if not improved:
            logger.warning("[reviser] LLM 返回空 analyses，跳过修正")
            return {}

        # 保留未修改的字段（analyzed_at 等）
        for idx, imp in enumerate(improved):
            if idx < len(analyses):
                imp.setdefault("analyzed_at", analyses[idx].get("analyzed_at", ""))

        logger.info("[reviser] 修正完成: %d 条 analyses", len(improved))
        return {"analyses": improved, "cost_tracker": tracker}

    except Exception as exc:
        logger.error("[reviser] 修正异常: %s", exc)
        return {}


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    print("=" * 60)
    print("Reviser 修正模块测试")
    print("=" * 60)

    from workflows.state import init_state

    state = init_state()
    state["analyses"] = [
        {
            "source_index": 0,
            "summary": "这是一个测试摘要，内容较为简单。",
            "tags": ["AI"],
            "category": "tool",
            "score": 0.6,
            "analyzed_at": "2026-05-24T00:00:00Z",
        },
        {
            "source_index": 1,
            "summary": "另一个测试摘要，技术深度不够。",
            "tags": ["Python"],
            "category": "unknown",
            "score": 0.5,
            "analyzed_at": "2026-05-24T00:00:00Z",
        },
    ]
    state["review_feedback"] = (
        "摘要过于简单，需要补充更多技术细节；"
        "标签太少，请补充相关技术标签；"
        "分类不够准确，请重新评估。"
    )

    print("\n--- 测试 revise_node ---")
    result = revise_node(state)

    if result:
        improved = result["analyses"]
        print(f"修正后 analyses: {len(improved)} 条")
        for ana in improved:
            print(
                f"  [{ana.get('source_index')}] "
                f"score={ana.get('score'):.2f}, "
                f"category={ana.get('category')}, "
                f"tags={ana.get('tags')}"
            )
            print(f"    summary: {ana.get('summary', '')[:80]}...")
        print(f"cost_tracker: {result['cost_tracker']}")
    else:
        print("修正被跳过（analyses 或 feedback 为空）")

    print(f"\n{'=' * 60}")
    print("测试结束")
    print("=" * 60)
