"""LangGraph 工作流组装：采集 → 分析 → 组织 → 审核 → (3 路分支)。

使用 StateGraph 将节点编排为有向图：
    collect → analyze → organize → review
                                       ├─ 通过 ──────────────→ organize → save → END
                                       ├─ 不通过 & iter<3 ──→ revise → review (循环)
                                       └─ 不通过 & iter>=3 ─→ human_flag → END

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

from langgraph.graph import END, StateGraph

from workflows.human_flag import human_flag_node
from workflows.nodes import (
    accumulate_usage,
    analyze_node,
    collect_node,
    organize_node,
    review_node as review_node_legacy,
    review_node_test,
    save_node,
)
from workflows.planner import planner_node
from workflows.reviser import revise_node
from workflows.reviewer import review_node
from workflows.state import KBState, init_state

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
#  路由函数
# ═══════════════════════════════════════════════════════════════

def _route_after_review(state: KBState) -> str:
    """审核后的 3 路条件路由器。

    分支逻辑：
        - 通过 → organize（重新整理后保存）
        - 不通过且 iteration < 3 → revise（修正后重审）
        - 不通过且 iteration >= 3 → human_flag（人工审核）

    Args:
        state: 当前工作流状态，必须包含 review_passed、iteration。

    Returns:
        str: "organize" / "revise" / "human_flag"
    """
    passed = state.get("review_passed", False)
    iteration = state.get("iteration", 0)
    plan = state.get("plan", {})
    max_iterations = plan.get("max_iterations", 3)

    if passed:
        logger.info("[graph] 审核通过，进入 organize 最终整理")
        return "organize"

    if iteration < max_iterations:
        logger.info(
            "[graph] 审核未通过 (iteration=%d < %d)，进入 revise 修正",
            iteration,
            max_iterations,
        )
        return "revise"

    logger.warning(
        "[graph] 审核未通过且 iteration=%d >= %d，进入 human_flag 人工审核",
        iteration,
        max_iterations,
    )
    return "human_flag"


def _route_after_organize(state: KBState) -> str:
    """组织后的条件路由器。

    首次 organize（review 前）：→ review
    再次 organize（review 通过后）：→ save

    Args:
        state: 当前工作流状态。

    Returns:
        str: "review" 或 "save"
    """
    if state.get("review_passed"):
        logger.info("[graph] organize 后进入 save")
        return "save"
    logger.info("[graph] organize 后进入 review")
    return "review"


# ═══════════════════════════════════════════════════════════════
#  build_graph
# ═══════════════════════════════════════════════════════════════

def build_graph() -> Any:
    """构建并编译 LangGraph 工作流。

    3 路条件分支：通过 / 修正循环 / 人工审核。

    Returns:
        Any: 编译后的 LangGraph 应用实例。
    """
    logger.info("[graph] 构建工作流图...")

    builder = StateGraph(KBState)

    # ── 注册节点 ───────────────────────────────────────────
    builder.add_node("planner", planner_node)
    builder.add_node("collect", collect_node)
    builder.add_node("analyze", analyze_node)
    builder.add_node("organize", organize_node)
    builder.add_node("review", review_node)
    builder.add_node("revise", revise_node)
    builder.add_node("human_flag", human_flag_node)
    builder.add_node("save", save_node)

    # ── 固定边 ─────────────────────────────────────────────
    builder.add_edge("planner", "collect")
    builder.add_edge("collect", "analyze")
    builder.add_edge("analyze", "organize")

    # organize 后条件路由：首次→review，通过后再整理→save
    builder.add_conditional_edges(
        "organize",
        _route_after_organize,
        {"review": "review", "save": "save"},
    )

    # ── review 后 3 路条件分支 ─────────────────────────────
    builder.add_conditional_edges(
        "review",
        _route_after_review,
        {
            "organize": "organize",
            "revise": "revise",
            "human_flag": "human_flag",
        },
    )

    # ── 修正循环边 ─────────────────────────────────────────
    builder.add_edge("revise", "review")

    # ── 结束边 ─────────────────────────────────────────────
    builder.add_edge("human_flag", END)
    builder.add_edge("save", END)

    # ── 入口点 ─────────────────────────────────────────────
    builder.set_entry_point("planner")

    app = builder.compile()
    logger.info("[graph] 工作流编译完成")
    return app


# ═══════════════════════════════════════════════════════════════
#  run_workflow
# ═══════════════════════════════════════════════════════════════

def run_workflow() -> KBState:
    """执行完整工作流并返回最终状态。"""
    app = build_graph()
    initial_state = init_state()

    logger.info("[graph] 开始执行工作流...")
    print("=" * 60)
    print("LangGraph 工作流执行")
    print("=" * 60)

    final_state: KBState = initial_state
    for chunk in app.stream(initial_state, stream_mode="updates"):
        for node_name, output in chunk.items():
            if node_name == END:
                continue


            print(f"\n[{'─' * 58}]")
            print(f"节点: {node_name}")
            print(f"[{'─' * 58}]")

            if node_name == "planner":
                plan = output.get("plan", {})
                print(f"  策略: {plan.get('strategy_name', 'unknown')}")
                print(f"  target: {plan.get('target_count', 0)}")
                print(f"  per_source_limit: {plan.get('per_source_limit', 0)}")
                print(f"  max_iterations: {plan.get('max_iterations', 0)}")

            elif node_name == "collect":
                sources = output.get("sources", [])
                print(f"  采集到 {len(sources)} 条数据")
                for s in sources[:3]:
                    print(f"    - {s.get('title', '')}: ⭐{s.get('stars', 0)}")

            elif node_name == "analyze":
                analyses = output.get("analyses", [])
                print(f"  分析完成 {len(analyses)} 条")
                for a in analyses[:3]:
                    print(f"    - score={a.get('score', 0):.2f}")

            elif node_name == "organize":
                articles = output.get("articles", [])
                print(f"  组织后 {len(articles)} 条 article")

            elif node_name == "review":
                passed = output.get("review_passed", False)
                iteration = output.get("iteration", 0)
                print(f"  审核结果: passed={passed}, iteration={iteration}")
                feedback = output.get("review_feedback", "")
                if feedback:
                    print(f"  反馈: {feedback[:60]}...")

            elif node_name == "revise":
                analyses = output.get("analyses", [])
                print(f"  修正后 {len(analyses)} 条 analyses")

            elif node_name == "human_flag":
                flagged = output.get("human_flagged", [])
                print(f"  人工标记 {len(flagged)} 条")
                for f in flagged[:2]:
                    print(f"    - {f.get('id', '')}: {f.get('flag_reason', '')}")

            elif node_name == "save":
                tracker = output.get("cost_tracker", {})
                print(f"  保存完成")
                print(f"  Token: {tracker.get('total_tokens', 0)}")

            final_state.update(output)

    print(f"\n{'=' * 60}")
    print("工作流执行完成")
    print("=" * 60)
    print(f"articles: {len(final_state.get('articles', []))}")
    print(f"passed: {final_state.get('review_passed', False)}")
    print(f"iteration: {final_state.get('iteration', 0)}")
    print(f"total_tokens: {final_state.get('cost_tracker', {}).get('total_tokens', 0)}")
    print("=" * 60)

    _print_cost_report(final_state)

    return final_state


def _print_cost_report(state: KBState) -> None:
    """打印工作流成本报告。

    汇总 CostGuard 记录和 cost_tracker 中的 Token 用量，
    按节点分组展示调用次数、Token 数和预估成本。

    Args:
        state: 最终工作流状态，包含 cost_tracker。
    """
    print(f"\n{'=' * 60}")
    print("成本报告")
    print("=" * 60)

    tracker = state.get("cost_tracker", {})
    total_prompt = tracker.get("total_prompt_tokens", 0)
    total_completion = tracker.get("total_completion_tokens", 0)
    total_tokens = tracker.get("total_tokens", 0)
    calls_by_node = tracker.get("calls_by_node", {})

    try:
        from workflows.model_client import get_cost_guard

        cost_guard = get_cost_guard()
        report = cost_guard.get_report()
        summary = report.get("summary", {})
        by_node = report.get("by_node", {})

        print(f"\n总调用次数: {summary.get('total_records', 0)} 次")
        print(f"总 Prompt Tokens: {summary.get('total_prompt_tokens', total_prompt):,}")
        print(f"总 Completion Tokens: {summary.get('total_completion_tokens', total_completion):,}")
        print(f"总 Tokens: {summary.get('total_prompt_tokens', 0) + summary.get('total_completion_tokens', 0):,}")
        print(f"预估成本: {summary.get('total_cost_yuan', 0.0):.6f} 元")
        print(f"预算上限: {summary.get('budget_yuan', 1.0):.4f} 元")
        print(f"预算使用率: {summary.get('usage_ratio', 0.0):.2%}")

        if by_node:
            print(f"\n{'─' * 60}")
            print("按节点统计:")
            print("─" * 60)
            for node_name, stats in sorted(by_node.items()):
                print(
                    f"  {node_name:20s}  "
                    f"调用 {stats.get('call_count', 0):3d} 次  "
                    f"Tokens: {stats.get('total_prompt_tokens', 0):6,} / {stats.get('total_completion_tokens', 0):6,}  "
                    f"成本: {stats.get('total_cost_yuan', 0.0):.6f} 元"
                )

        try:
            report_path = cost_guard.save_report()
            print(f"\n成本报告已保存: {report_path}")
        except Exception as exc:
            logger.warning("[graph] 保存成本报告失败: %s", exc)

    except Exception as exc:
        logger.warning("[graph] CostGuard 报告生成失败，使用基础统计: %s", exc)
        print(f"\n总 Prompt Tokens: {total_prompt:,}")
        print(f"总 Completion Tokens: {total_completion:,}")
        print(f"总 Tokens: {total_tokens:,}")

        if calls_by_node:
            print(f"\n{'─' * 60}")
            print("按节点调用次数:")
            print("─" * 60)
            for node_name, count in sorted(calls_by_node.items()):
                print(f"  {node_name:20s}: {count} 次")

    print(f"{'=' * 60}")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    final_state = run_workflow()

    if not final_state.get("articles"):
        print("\n注意：本次执行未获取到有效数据。")
        print("节点连通性：collect → analyze → organize → review → (save/revise/human_flag)")
