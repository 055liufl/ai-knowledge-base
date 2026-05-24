"""Reviewer 审核模块：对 analyses 进行五维度加权评分。

实现独立的 review_node 函数，支持：
    - 5 维度评分（1-10 分）
    - 代码重算加权总分（不依赖模型算术）
    - 只审核前 5 条 analyses（控 token）
    - LLM 失败时自动通过（不阻塞）

编码规范：
    - 严格遵循 PEP 8
    - 使用 Google 风格 docstring
    - 使用 logging 而非 print
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from pipeline.model_client import Usage
from workflows.model_client import chat_json
from workflows.nodes import accumulate_usage
from workflows.state import KBState

logger = logging.getLogger(__name__)

# ── 权重配置 ────────────────────────────────────────────────
_WEIGHTS: dict[str, float] = {
    "summary_quality": 0.25,
    "technical_depth": 0.25,
    "relevance": 0.20,
    "originality": 0.15,
    "formatting": 0.15,
}
_PASS_THRESHOLD = 7.0

# ── System Prompt ───────────────────────────────────────────
_REVIEW_SYSTEM_PROMPT = (
    "你是一个严格的技术内容审核员。请对给定的分析结果进行五维度评分。\n\n"
    "评分维度（每项 1-10 分，10 分最高）：\n"
    "1. summary_quality: 摘要质量 — 中文是否通顺、信息是否准确完整\n"
    "2. technical_depth: 技术深度 — 是否抓住了核心技术要点\n"
    "3. relevance: 相关性 — 与 AI/LLM/Agent 等领域是否高度相关\n"
    "4. originality: 原创性 — 是否有独特见解，非泛泛而谈\n"
    "5. formatting: 格式规范 — JSON 结构、标签、分类是否正确\n\n"
    "输出 JSON 格式（不要 markdown 代码块）：\n"
    '{"reviews": [{"index": 0, "summary_quality": 8, "technical_depth": 7, '
    '"relevance": 9, "originality": 6, "formatting": 8, '
    '"feedback": "具体改进建议"}, ...]}'
)


def _calculate_weighted_score(scores: dict[str, Any]) -> float:
    """根据权重计算加权总分。

    Args:
        scores: 包含五个维度评分的字典。

    Returns:
        float: 加权总分（0.0-10.0）。
    """
    total = 0.0
    for dim, weight in _WEIGHTS.items():
        total += float(scores.get(dim, 0)) * weight
    return round(total, 2)


def review_node(state: KBState) -> dict[str, Any]:
    """审核节点：对 analyses 进行五维度加权评分。

    审核对象：state["analyses"]（organize 之前的分析结果）
    只审核前 5 条，temperature=0.1 保证评分一致性。
    LLM 调用失败时自动通过，不阻塞流程。

    Args:
        state: 当前工作流状态，必须包含 analyses、iteration、cost_tracker。

    Returns:
        dict[str, Any]: {
            "review_passed": bool,
            "review_feedback": str,
            "iteration": int,
            "cost_tracker": dict,
        }
    """
    iteration = state.get("iteration", 0)
    analyses = state.get("analyses", [])
    tracker = state.get("cost_tracker", {}).copy()
    plan = state.get("plan", {})
    pass_threshold = plan.get("pass_threshold", 7.0)

    logger.info("[reviewer] 开始审核 analyses (iteration=%d, total=%d, pass_threshold=%.1f)...", iteration, len(analyses), pass_threshold)

    if not analyses:
        logger.warning("[reviewer] analyses 为空，直接通过")
        return {
            "review_passed": True,
            "review_feedback": "无内容可审核。",
            "iteration": iteration,
            "cost_tracker": tracker,
        }

    # 只审核前 5 条
    target = analyses[:5]
    review_input = []
    for idx, ana in enumerate(target):
        review_input.append({
            "index": idx,
            "title": ana.get("title", "")[:50],
            "summary": ana.get("summary", "")[:150],
            "tags": ana.get("tags", []),
            "category": ana.get("category", ""),
            "score": ana.get("score", 0.0),
        })

    prompt = (
        "请对以下分析结果进行五维度评分：\n\n"
        f"{__import__('json').dumps(review_input, ensure_ascii=False, indent=2)}\n\n"
        "请返回 JSON 格式的评分结果。"
    )

    try:
        result, usage = chat_json(
            node_name="reviewer",
            prompt=prompt,
            system_prompt=_REVIEW_SYSTEM_PROMPT,
            temperature=0.1,
        )
        accumulate_usage(tracker, usage, node_name="reviewer")

        if "error" in result:
            logger.warning("[reviewer] LLM 返回错误: %s", result.get("error"))
            return {
                "review_passed": True,
                "review_feedback": f"LLM 返回错误，自动通过: {result.get('error')}",
                "iteration": iteration,
                "cost_tracker": tracker,
            }

        reviews = result.get("reviews", [])
        if not reviews:
            logger.warning("[reviewer] LLM 返回空 reviews，自动通过")
            return {
                "review_passed": True,
                "review_feedback": "LLM 返回空评分，自动通过。",
                "iteration": iteration,
                "cost_tracker": tracker,
            }

        # 用代码重算加权总分
        passed_count = 0
        feedback_lines = []
        for r in reviews:
            idx = r.get("index", 0)
            scores = {
                "summary_quality": r.get("summary_quality", 0),
                "technical_depth": r.get("technical_depth", 0),
                "relevance": r.get("relevance", 0),
                "originality": r.get("originality", 0),
                "formatting": r.get("formatting", 0),
            }
            weighted = _calculate_weighted_score(scores)
            passed = weighted >= pass_threshold

            if passed:
                passed_count += 1

            feedback_lines.append(
                f"条目 {idx}: 加权分={weighted:.2f}, "
                f"summary_quality={scores['summary_quality']}, "
                f"technical_depth={scores['technical_depth']}, "
                f"relevance={scores['relevance']}, "
                f"originality={scores['originality']}, "
                f"formatting={scores['formatting']} — "
                f"{'通过' if passed else '未通过'}"
            )

            # 附加 LLM 的反馈
            llm_feedback = r.get("feedback", "")
            if llm_feedback and llm_feedback != "无":
                feedback_lines.append(f"  反馈: {llm_feedback}")

        overall_passed = passed_count >= len(reviews) * 0.6  # 60% 通过即整体通过
        summary = (
            f"审核 {len(reviews)} 条 analyses，"
            f"{passed_count}/{len(reviews)} 条通过（加权分 >= {pass_threshold}）。\n"
            + "\n".join(feedback_lines)
        )

        logger.info(
            "[reviewer] 审核完成: passed=%s, passed_count=%d/%d",
            overall_passed,
            passed_count,
            len(reviews),
        )

        return {
            "review_passed": overall_passed,
            "review_feedback": summary,
            "iteration": iteration + 1,
            "cost_tracker": tracker,
        }

    except Exception as exc:
        logger.error("[reviewer] 审核异常: %s", exc)
        return {
            "review_passed": True,
            "review_feedback": f"审核异常，自动通过: {exc}",
            "iteration": iteration,
            "cost_tracker": tracker,
        }


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    print("=" * 60)
    print("Reviewer 审核模块测试")
    print("=" * 60)

    # 测试 _calculate_weighted_score
    scores = {
        "summary_quality": 8,
        "technical_depth": 7,
        "relevance": 9,
        "originality": 6,
        "formatting": 8,
    }
    score = _calculate_weighted_score(scores)
    print(f"\n加权分计算: {scores}")
    print(f"  结果: {score:.2f} (阈值: {_PASS_THRESHOLD})")
    assert abs(score - (8 * 0.25 + 7 * 0.25 + 9 * 0.20 + 6 * 0.15 + 8 * 0.15)) < 0.01
    print("  计算正确 ✓")

    # 测试 review_node
    from workflows.state import init_state

    state = init_state()
    state["analyses"] = [
        {
            "title": "test/repo1",
            "summary": "这是一个测试仓库，用于演示 AI 功能。",
            "tags": ["AI", "Python"],
            "category": "tool",
            "score": 0.85,
        },
        {
            "title": "test/repo2",
            "summary": "另一个测试仓库，用于 Agent 开发。",
            "tags": ["Agent", "TypeScript"],
            "category": "framework",
            "score": 0.55,
        },
    ]

    print("\n--- 测试 review_node ---")
    try:
        result = review_node(state)
        print(f"review_passed: {result['review_passed']}")
        print(f"iteration: {result['iteration']}")
        print(f"feedback:\n{result['review_feedback'][:300]}...")
        print(f"cost_tracker: {result['cost_tracker']}")
    except Exception as exc:
        print(f"异常: {exc}")

    print(f"\n{'=' * 60}")
    print("测试结束")
    print("=" * 60)
