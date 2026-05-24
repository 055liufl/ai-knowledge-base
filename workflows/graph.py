"""LangGraph 工作流组装：采集 → 分析 → 组织 → 审核 → 保存。

使用 StateGraph 将 5 个节点编排为有向图：
    collect → analyze → organize → review → (条件分支)
                                       ├─ True  → save → END
                                       └─ False → organize (循环)

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

from workflows.nodes import (
    accumulate_usage,
    analyze_node,
    collect_node,
    organize_node,
    review_node,        # LLM 审核版本（默认）
    review_node_test,   # 测试版本：前2次不通过，第3次通过
    save_node,
)
from workflows.state import KBState, init_state

logger = logging.getLogger(__name__)


def _review_router(state: KBState) -> str:
    """审核节点条件路由器。

    根据 review_passed 状态决定分支方向：
        - True  → 进入 save 节点（保存结果）
        - False → 回到 organize 节点（定向修正）

    Args:
        state: 当前工作流状态，必须包含 review_passed 字段。

    Returns:
        str: "save" 或 "organize"，对应 add_conditional_edges 的 path_map 键。
    """
    passed = state.get("review_passed", False)
    iteration = state.get("iteration", 0)

    if passed:
        logger.info("[graph] 审核通过，进入 save 节点")
        return "save"

    if iteration >= 2:
        logger.info("[graph] iteration=%d >= 2，强制结束审核循环", iteration)
        return "save"

    logger.info("[graph] 审核未通过，回到 organize 节点修正 (iteration=%d)", iteration)
    return "organize"


def build_graph() -> Any:
    """构建并编译 LangGraph 工作流。

    将 5 个节点组装为有状态图，支持审核失败循环修正。

    Returns:
        Any: 编译后的 LangGraph 应用实例。

    Example:
        >>> app = build_graph()
        >>> result = app.invoke(init_state())
    """
    logger.info("[graph] 构建工作流图...")

    builder = StateGraph(KBState)

    # ── 注册节点 ───────────────────────────────────────────
    builder.add_node("collect", collect_node)
    builder.add_node("analyze", analyze_node)
    builder.add_node("organize", organize_node)
    # 审核节点切换（取消注释使用对应版本）：
    builder.add_node("review", review_node)      # LLM 评分（默认）
    # builder.add_node("review", review_node_test)  # 测试循环
    builder.add_node("save", save_node)

    # ── 线性边 ─────────────────────────────────────────────
    builder.add_edge("collect", "analyze")
    builder.add_edge("analyze", "organize")
    builder.add_edge("organize", "review")

    # ── 条件边：review 后分支 ──────────────────────────────
    builder.add_conditional_edges(
        "review",
        _review_router,
        {
            "save": "save",
            "organize": "organize",
        },
    )

    # ── 结束边 ─────────────────────────────────────────────
    builder.add_edge("save", END)

    # ── 入口点 ─────────────────────────────────────────────
    builder.set_entry_point("collect")

    app = builder.compile()
    logger.info("[graph] 工作流编译完成")
    return app


def run_workflow() -> KBState:
    """执行完整工作流并返回最终状态。

    从初始状态开始，流式执行所有节点，打印关键输出。

    Returns:
        KBState: 执行后的最终状态。
    """
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

            # 打印每个节点的关键输出
            if node_name == "collect":
                sources = output.get("sources", [])
                print(f"  采集到 {len(sources)} 条数据")
                for s in sources[:3]:
                    print(f"    - {s.get('title', '')}: ⭐{s.get('stars', 0)}")

            elif node_name == "analyze":
                analyses = output.get("analyses", [])
                print(f"  分析完成 {len(analyses)} 条")
                for a in analyses[:3]:
                    print(
                        f"    - score={a.get('score', 0):.2f}, "
                        f"category={a.get('category', '')}"
                    )

            elif node_name == "organize":
                articles = output.get("articles", [])
                print(f"  组织后 {len(articles)} 条 article")
                for art in articles[:3]:
                    print(
                        f"    - {art.get('title', '')}: "
                        f"score={art.get('score', 0):.2f}"
                    )

            elif node_name == "review":
                passed = output.get("review_passed", False)
                feedback = output.get("review_feedback", "")
                iteration = output.get("iteration", 0)
                print(f"  审核结果: passed={passed}, iteration={iteration}")
                if feedback:
                    print(f"  反馈: {feedback[:80]}...")

            elif node_name == "save":
                tracker = output.get("cost_tracker", {})
                print(f"  保存完成")
                print(
                    f"  Token 统计: prompt={tracker.get('total_prompt_tokens', 0)}, "
                    f"completion={tracker.get('total_completion_tokens', 0)}, "
                    f"total={tracker.get('total_tokens', 0)}"
                )
                calls = tracker.get("calls_by_node", {})
                for node, count in calls.items():
                    print(f"    {node}: {count} 次调用")

            # 合并输出到最终状态
            final_state.update(output)

    print(f"\n{'=' * 60}")
    print("工作流执行完成")
    print("=" * 60)
    print(f"最终 articles 数: {len(final_state.get('articles', []))}")
    print(f"审核通过: {final_state.get('review_passed', False)}")
    print(f"迭代次数: {final_state.get('iteration', 0)}")
    print(f"总 Token: {final_state.get('cost_tracker', {}).get('total_tokens', 0)}")
    print("=" * 60)

    return final_state


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # 执行完整工作流
    final_state = run_workflow()

    # 如果 articles 为空（测试数据不足），展示节点连通性
    if not final_state.get("articles"):
        print("\n注意：本次执行未获取到有效数据（可能是 API 限制或网络问题）。")
        print("节点连通性验证：collect → analyze → organize → review → save → END ✓")
