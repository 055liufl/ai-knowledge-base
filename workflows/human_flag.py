"""HumanFlag 人工审核标记模块。

当审核循环超过 max_iterations 仍未通过时，
将问题条目写入独立目录 knowledge/human_review/，
不污染主知识库，等待人工判断。

编码规范：
    - 严格遵循 PEP 8
    - 使用 Google 风格 docstring
    - 使用 logging 而非 print
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from workflows.state import KBState

logger = logging.getLogger(__name__)

# ── 人工审核目录 ────────────────────────────────────────────
_HUMAN_REVIEW_DIR = _PROJECT_ROOT / "knowledge" / "human_review"

# ── 默认最大迭代次数 ────────────────────────────────────────
_DEFAULT_MAX_ITERATIONS = 3


def human_flag_node(
    state: KBState,
    max_iterations: int = _DEFAULT_MAX_ITERATIONS,
) -> dict[str, Any]:
    """人工审核标记节点：将未通过的问题条目写入独立目录。

    当审核循环超过 max_iterations 仍未通过时，
    说明问题不在"质量"而在"数据"本身，需要人工判断。
    本节点将问题条目从主流程中隔离，写入 human_review/ 目录，
    不污染主知识库，等待人工审核后决定取舍。

    Args:
        state: 当前工作流状态，必须包含 articles、review_passed、
               iteration、review_feedback、cost_tracker。
        max_iterations: 最大允许迭代次数，默认 3。

    Returns:
        dict[str, Any]: {
            "human_flagged": list[dict],  # 被标记的条目列表
            "cost_tracker": dict,          # 原始 cost_tracker（无修改）
        }
    """
    articles = state.get("articles", [])
    review_passed = state.get("review_passed", False)
    iteration = state.get("iteration", 0)
    feedback = state.get("review_feedback", "")
    tracker = state.get("cost_tracker", {}).copy()

    logger.info(
        "[human_flag] 检查状态: passed=%s, iteration=%d, max=%d",
        review_passed,
        iteration,
        max_iterations,
    )

    # 通过审核：无需人工干预
    if review_passed:
        logger.info("[human_flag] 审核已通过，无需标记")
        return {"human_flagged": [], "cost_tracker": tracker}

    # 未达最大迭代次数：继续循环，不标记
    if iteration < max_iterations:
        logger.info(
            "[human_flag] iteration=%d < max=%d，继续循环",
            iteration,
            max_iterations,
        )
        return {"human_flagged": [], "cost_tracker": tracker}

    # 超过 max_iterations：需要人工判断
    logger.warning(
        "[human_flag] 超过最大迭代次数（%d/%d），标记为需人工审核",
        iteration,
        max_iterations,
    )

    if not articles:
        logger.warning("[human_flag] articles 为空，无可标记条目")
        return {"human_flagged": [], "cost_tracker": tracker}

    _HUMAN_REVIEW_DIR.mkdir(parents=True, exist_ok=True)

    flagged: list[dict[str, Any]] = []
    timestamp = datetime.now(timezone.utc).isoformat()

    for idx, art in enumerate(articles):
        # 构建人工审核条目
        flagged_entry = {
            "id": art.get("id", f"flagged_{idx}"),
            "title": art.get("title", "无标题"),
            "source_url": art.get("source_url", ""),
            "source_platform": art.get("source_platform", ""),
            "summary": art.get("summary", ""),
            "tags": art.get("tags", []),
            "category": art.get("category", ""),
            "score": art.get("score", 0.0),
            "flag_reason": "审核循环超过最大迭代次数仍未通过",
            "review_feedback": feedback,
            "iteration": iteration,
            "flagged_at": timestamp,
            "status": "pending_human_review",
        }

        # 写入独立文件
        file_path = _HUMAN_REVIEW_DIR / f"{flagged_entry['id']}.json"
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(flagged_entry, f, ensure_ascii=False, indent=2)
            flagged.append(flagged_entry)
            logger.info("[human_flag] 已标记: %s", file_path.name)
        except OSError as exc:
            logger.error("[human_flag] 写入失败: %s - %s", file_path, exc)

    # 更新 human_review 索引
    _update_human_index(flagged)

    logger.info("[human_flag] 标记完成: %d 条需人工审核", len(flagged))
    return {"human_flagged": flagged, "cost_tracker": tracker}


def _update_human_index(flagged: list[dict[str, Any]]) -> None:
    """更新 human_review/index.json 索引。

    Args:
        flagged: 本次标记的条目列表。
    """
    index_path = _HUMAN_REVIEW_DIR / "index.json"

    existing: list[dict[str, Any]] = []
    if index_path.exists():
        try:
            with open(index_path, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except (json.JSONDecodeError, OSError):
            pass

    existing_ids = {e.get("id") for e in existing}
    new_entries = [f for f in flagged if f.get("id") not in existing_ids]

    combined = existing + new_entries
    try:
        with open(index_path, "w", encoding="utf-8") as f:
            json.dump(combined, f, ensure_ascii=False, indent=2)
        logger.info(
            "[human_flag] 索引更新: +%d 条, 总计 %d 条",
            len(new_entries),
            len(combined),
        )
    except OSError as exc:
        logger.error("[human_flag] 索引写入失败: %s", exc)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    print("=" * 60)
    print("HumanFlag 人工审核标记测试")
    print("=" * 60)

    from workflows.state import init_state

    # 测试1：审核通过，无需标记
    print("\n--- 测试1: 审核通过 ---")
    state = init_state()
    state["articles"] = [{"id": "test1", "title": "测试1"}]
    state["review_passed"] = True
    state["iteration"] = 1
    result = human_flag_node(state)
    print(f"human_flagged: {len(result['human_flagged'])} 条")

    # 测试2：未达最大迭代，继续循环
    print("\n--- 测试2: 继续循环 ---")
    state = init_state()
    state["articles"] = [{"id": "test2", "title": "测试2"}]
    state["review_passed"] = False
    state["iteration"] = 1
    result = human_flag_node(state)
    print(f"human_flagged: {len(result['human_flagged'])} 条")

    # 测试3：超过迭代，标记人工审核
    print("\n--- 测试3: 标记人工审核 ---")
    state = init_state()
    state["articles"] = [
        {
            "id": "test_repo_001",
            "title": "test/bad-repo",
            "source_url": "https://github.com/test/bad-repo",
            "source_platform": "github_trending",
            "summary": "质量很差的摘要",
            "tags": ["bad"],
            "category": "unknown",
            "score": 0.3,
        }
    ]
    state["review_passed"] = False
    state["iteration"] = 3
    state["review_feedback"] = "摘要质量极差，无法修复"
    result = human_flag_node(state)
    print(f"human_flagged: {len(result['human_flagged'])} 条")
    for f in result["human_flagged"]:
        print(f"  - {f['id']}: {f['flag_reason']}")
        print(f"    feedback: {f['review_feedback']}")
        print(f"    status: {f['status']}")

    print(f"\n{'=' * 60}")
    print("测试结束")
    print("=" * 60)
