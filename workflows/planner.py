"""LangGraph 工作流规划节点。

实现知识库采集的策略规划功能：
    - plan_strategy: 根据目标采集量返回对应策略 dict
    - planner_node: LangGraph 节点包装，将策略注入工作流状态

编码规范：
    - 严格遵循 PEP 8
    - 使用 Google 风格 docstring
    - 使用 logging 而非 print
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict

from workflows.state import KBState

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 策略配置
# ---------------------------------------------------------------------------
_DEFAULT_TARGET_COUNT = 10
_ENV_TARGET_KEY = "PLANNER_TARGET_COUNT"

_STRATEGIES = {
    "lite": {
        "per_source_limit": 5,
        "relevance_threshold": 0.7,
        "max_iterations": 1,
        "rationale": (
            "目标采集量较少（<10），采用轻量策略："
            "每源最多采集 5 条，提高相关性阈值到 0.7 以减少低质数据，"
            "仅允许 1 轮审核迭代，快速产出结果。"
        ),
    },
    "standard": {
        "per_source_limit": 10,
        "relevance_threshold": 0.5,
        "max_iterations": 2,
        "rationale": (
            "目标采集量中等（10-19），采用标准策略："
            "每源最多采集 10 条，相关性阈值设为 0.5 兼顾数量与质量，"
            "允许 2 轮审核迭代，在质量与效率间取得平衡。"
        ),
    },
    "full": {
        "per_source_limit": 20,
        "relevance_threshold": 0.4,
        "max_iterations": 3,
        "rationale": (
            "目标采集量较大（>=20），采用完整策略："
            "每源最多采集 20 条，降低相关性阈值到 0.4 以覆盖更多潜在素材，"
            "允许 3 轮审核迭代，最大化内容产出与质量把关。"
        ),
    },
}


# ---------------------------------------------------------------------------
# 策略规划
# ---------------------------------------------------------------------------
def plan_strategy(target_count: int | None = None) -> Dict[str, Any]:
    """根据目标采集量返回对应的采集策略。

    三档策略：
        - lite    : target < 10
        - standard: 10 <= target < 20
        - full    : target >= 20

    target_count 为 None 时，从环境变量 PLANNER_TARGET_COUNT 读取，
    若环境变量未设置则使用默认值 10。

    Args:
        target_count: 目标采集条数。None 表示从环境变量读取。

    Returns:
        Dict[str, Any]: 策略字典，包含以下字段：
            - strategy_name     : 策略名称（"lite"/"standard"/"full"）
            - per_source_limit  : 每来源最大采集条数
            - relevance_threshold: 相关性阈值（0.0-1.0）
            - max_iterations    : 审核最大迭代次数
            - rationale         : 策略选择理由说明
            - target_count      : 实际使用的目标采集量
    """
    if target_count is None:
        env_value = os.environ.get(_ENV_TARGET_KEY, str(_DEFAULT_TARGET_COUNT))
        try:
            target_count = int(env_value)
        except (ValueError, TypeError):
            logger.warning(
                "[%s] 环境变量 %s 值无效 (%r)，使用默认值 %d",
                __name__,
                _ENV_TARGET_KEY,
                env_value,
                _DEFAULT_TARGET_COUNT,
            )
            target_count = _DEFAULT_TARGET_COUNT

    if target_count < 10:
        strategy_name = "lite"
    elif target_count < 20:
        strategy_name = "standard"
    else:
        strategy_name = "full"

    strategy = dict(_STRATEGIES[strategy_name])
    strategy["strategy_name"] = strategy_name
    strategy["target_count"] = target_count

    logger.info(
        "[plan_strategy] 策略=%s, target=%d, per_source_limit=%d, "
        "threshold=%.1f, max_iterations=%d",
        strategy_name,
        target_count,
        strategy["per_source_limit"],
        strategy["relevance_threshold"],
        strategy["max_iterations"],
    )
    logger.debug("[plan_strategy] rationale: %s", strategy["rationale"])

    return strategy


# ---------------------------------------------------------------------------
# LangGraph 节点包装
# ---------------------------------------------------------------------------
def planner_node(state: KBState) -> Dict[str, Any]:
    """规划节点：根据目标采集量生成策略并注入状态。

    作为 LangGraph 工作流节点，接收 KBState，返回包含 plan 字段的更新字典。

    Args:
        state: 当前工作流共享状态。

    Returns:
        Dict[str, Any]: 状态更新，包含 {"plan": <策略字典>}。
    """
    logger.info("[planner_node] 开始生成采集策略...")

    # 优先从状态中读取 target_count，若不存在则从环境变量读取
    target_count = state.get("target_count")
    plan = plan_strategy(target_count)

    logger.info(
        "[planner_node] 策略生成完成: %s (target=%d)",
        plan["strategy_name"],
        plan["target_count"],
    )

    return {"plan": plan}


# ---------------------------------------------------------------------------
# 本地测试
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stdout,
    )

    print("=" * 60)
    print("planner.py 本地测试")
    print("=" * 60)

    for target in [5, 10, 15, 20, 50]:
        plan = plan_strategy(target)
        print(f"\n--- target={target} ---")
        for k, v in plan.items():
            print(f"  {k:20s}: {v}")

    print("\n" + "=" * 60)
    print("从环境变量读取测试 (PLANNER_TARGET_COUNT)...")
    print("=" * 60)
    os.environ[_ENV_TARGET_KEY] = "12"
    plan = plan_strategy()
    print(f"  环境变量=12 → 策略: {plan['strategy_name']}")

    os.environ[_ENV_TARGET_KEY] = "invalid"
    plan = plan_strategy()
    print(f"  环境变量=invalid → 策略: {plan['strategy_name']} (回退默认值)")

    del os.environ[_ENV_TARGET_KEY]
    plan = plan_strategy()
    print(f"  环境变量未设置 → 策略: {plan['strategy_name']} (回退默认值)")

    print("\n" + "=" * 60)
    print("planner_node 测试")
    print("=" * 60)
    from workflows.state import init_state

    state = init_state()
    state["target_count"] = 25
    result = planner_node(state)
    print(f"  输入 target_count=25 → 策略: {result['plan']['strategy_name']}")

    state2 = init_state()
    result2 = planner_node(state2)
    print(f"  无 target_count → 策略: {result2['plan']['strategy_name']}")

    print("\n" + "=" * 60)
    print("测试通过")
    print("=" * 60)
