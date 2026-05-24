"""LangGraph 工作流共享状态定义。

定义 KBState TypedDict，作为工作流各节点之间的共享状态容器。
遵循"报告式通信"原则：字段存储的是结构化摘要，不是原始数据。

编码规范：
    - 严格遵循 PEP 8
    - 使用 Google 风格 docstring
    - 使用 typing 模块确保类型安全
"""

from __future__ import annotations

from typing import Dict, List, Optional, TypedDict


class KBState(TypedDict, total=False):
    """知识库工作流共享状态。

    作为 LangGraph 工作流各节点之间的状态容器，
    每个节点接收 KBState，返回部分状态更新（dict）。

    遵循"报告式通信"原则：
        - sources: 采集到的原始数据摘要（非完整原始响应）
        - analyses: LLM 分析后的结构化摘要（含中文摘要、标签、评分）
        - articles: 格式化、去重后的知识条目（可直接入库的干净数据）
        - review_feedback: 审核意见的文本摘要（非完整审核报告）
        - review_passed: 审核结果的布尔标志
        - iteration: 当前审核循环计数（0-3，超过则强制通过）
        - cost_tracker: Token 用量和成本的累加统计
    """

    # -- 采集阶段 --
    sources: List[Dict[str, object]]
    """采集到的原始数据摘要列表。

    每个元素为一条原始数据的结构化摘要，包含：
        - platform: 来源平台标识（如 "github_trending", "rss_ai_research"）
        - raw_url: 原始数据链接
        - title: 原始标题（可能为英文）
        - fetched_at: 采集时间戳（ISO 8601 格式）
        - metadata: 平台相关的附加元数据（如 star 数、作者等）
    注意：存储的是摘要而非完整原始响应体。
    """

    # -- 分析阶段 --
    analyses: List[Dict[str, object]]
    """LLM 分析后的结构化结果列表。

    每个元素为一条数据的 LLM 分析输出，包含：
        - source_index: 对应 sources 列表的索引
        - summary: 中文摘要（200-500 字）
        - tags: 标签列表（如 ["LLM", "Agent", "RAG"]）
        - category: 技术分类（如 "tool", "framework", "paper"）
        - score: 质量评分（0.0-1.0，综合相关性/时效性/实用性）
        - analyzed_at: 分析时间戳
    由 analyze_node 节点生成，供 organize_node 过滤使用。
    """

    # -- 组织阶段 --
    articles: List[Dict[str, object]]
    """格式化、去重后的知识条目列表。

    每个元素为可直接入库的标准化知识条目，包含：
        - id: 唯一标识（如 "github_trending_20260524_dify"）
        - title: 中文标题
        - source_url: 原始链接
        - source_platform: 来源平台
        - summary: 中文摘要
        - tags: 标签列表
        - category: 技术分类
        - score: 最终质量评分（0.0-1.0）
        - language: 主要编程语言（如 "Python", "TypeScript"）
        - collected_at: 采集时间戳
        - status: 条目状态（"draft" / "published"）
    由 organize_node 节点生成，是 save_node 的写入目标。
    """

    # -- 审核阶段 --
    review_feedback: str
    """审核反馈意见文本。

    由 review_node 生成的审核意见摘要，
    在 iteration > 0 时传递给 organize_node 做定向修正。
    空字符串表示无反馈（首次迭代或已通过）。
    """

    review_passed: bool
    """审核是否通过的标志。

    True:  审核通过（overall_score >= 0.7），工作流可进入 save_node。
    False: 审核未通过，需要进入下一轮迭代修正。
    注意：iteration >= 2 时强制设为 True（最多 3 轮审核）。
    """

    iteration: int
    """当前审核循环次数。

    取值范围：0, 1, 2（最多 3 次迭代）。
    - 0: 首次通过 organize_node，尚未审核
    - 1: 第一次审核未通过，已反馈修正
    - 2: 第二次审核，若仍未通过则强制通过
    由 review_node 维护，用于控制审核循环终止条件。
    """

    # -- 规划阶段 --
    plan: Dict[str, object]
    """planner_node 生成的采集策略。

    包含策略名称、每源采集上限、相关性阈值、最大迭代次数、
    策略选择理由及目标采集量。
    由 planner_node 生成，供后续节点参考使用。
    """

    target_count: int
    """目标采集条数。

    由用户或外部系统传入，planner_node 据此选择对应策略。
    若未设置，planner_node 会从环境变量 PLANNER_TARGET_COUNT 读取。
    """

    # -- 成本追踪 --
    cost_tracker: Dict[str, object]
    """Token 用量和成本累加统计。

    记录整个工作流各节点的 LLM 调用成本，包含：
        - total_prompt_tokens: 累计输入 Token 数
        - total_completion_tokens: 累计输出 Token 数
        - total_tokens: 累计总 Token 数
        - total_cost_usd: 累计预估成本（USD）
        - calls_by_node: 各节点调用次数统计
          （如 {"analyze_node": 5, "review_node": 3}）
    由 accumulate_usage() 函数在各节点中累加更新。
    """


def init_state() -> KBState:
    """创建初始化的 KBState 实例。

    返回所有字段已设置默认值的 KBState 字典，
    作为工作流执行前的初始状态。

    Returns:
        KBState: 初始状态字典。
    """
    return KBState(
        sources=[],
        analyses=[],
        articles=[],
        plan={},
        target_count=10,
        review_feedback="",
        review_passed=False,
        iteration=0,
        cost_tracker={
            "total_prompt_tokens": 0,
            "total_completion_tokens": 0,
            "total_tokens": 0,
            "total_cost_usd": 0.0,
            "calls_by_node": {},
        },
    )


if __name__ == "__main__":
    state = init_state()
    print("=" * 50)
    print("KBState 初始状态验证")
    print("=" * 50)
    for key, value in state.items():
        print(f"{key:20s}: {value!r}")
    print("=" * 50)
    print("验证通过")
