"""AI 知识库评估测试套件。

使用 pytest 框架对工作流的分析质量进行自动化评估：
    - 本地验证：检查 EVAL_CASES 结构和基础逻辑
    - LLM-as-Judge：让 LLM 对分析结果打分（>=5）

编码规范：
    - 严格遵循 PEP 8
    - 使用 Google 风格 docstring
"""

from __future__ import annotations

import logging
import sys
import warnings
from pathlib import Path
from typing import Any, Callable, Dict, List

# ── 导入依赖 ────────────────────────────────────────────────
_PROJECT_ROOT = Path(__file__).parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import pytest

# ── 加载 .env ───────────────────────────────────────────────
try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).parent.parent / ".env")
except Exception:
    pass  # 无 .env 时不阻塞

# ── 屏蔽 PytestUnknownMarkWarning ───────────────────────────
try:
    warnings.filterwarnings(
        "ignore",
        category=pytest.PytestUnknownMarkWarning,
    )
except AttributeError:
    pass  # 兼容旧版 pytest

from workflows.model_client import chat

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
#  评估用例定义
# ═══════════════════════════════════════════════════════════════

EVAL_CASES: List[Dict[str, Any]] = [
    {
        "name": "正面案例：技术文章输入",
        "input": (
            "仓库名称: langchain-ai/langchain\n"
            "描述: LangChain 是一个用于开发基于语言模型应用的框架，"
            "支持链式调用、代理、RAG 等模式。\n"
            "编程语言: Python\n"
            "Stars: 98000\n"
            "Topics: llm, rag, agent, framework"
        ),
        "expected": {
            "summary_min_len": 50,
            "has_keywords": ["框架", "LLM", "RAG", "代理"],
            "score_range": (0.7, 1.0),
        },
    },
    {
        "name": "负面案例：无关内容输入",
        "input": (
            "仓库名称: random-user/cooking-recipes\n"
            "描述: 收集了 100 道家常菜的做法，适合厨房新手。\n"
            "编程语言: 无\n"
            "Stars: 15\n"
            "Topics: cooking, recipes, food"
        ),
        "expected": {
            "summary_max_len": 300,
            "score_range": (0.0, 0.5),
            "should_not_have": ["LLM", "AI", "大模型", "agent"],
        },
    },
    {
        "name": "边界案例：极短输入",
        "input": (
            "仓库名称: test/ai\n"
            "描述: AI\n"
            "编程语言: Python\n"
            "Stars: 1\n"
            "Topics: ai"
        ),
        "expected": {
            "should_not_crash": True,
            "score_range": (0.0, 1.0),
        },
    },
]


# ═══════════════════════════════════════════════════════════════
#  本地验证测试（不调用 LLM）
# ═══════════════════════════════════════════════════════════════

class TestEvalCasesStructure:
    """验证 EVAL_CASES 结构完整性。"""

    def test_cases_count(self) -> None:
        """至少包含 3 个用例。"""
        assert len(EVAL_CASES) >= 3, f"EVAL_CASES 数量不足: {len(EVAL_CASES)}"

    def test_case_fields(self) -> None:
        """每个用例包含 name、input、expected 字段。"""
        for case in EVAL_CASES:
            assert "name" in case, f"用例缺少 name 字段: {case}"
            assert "input" in case, f"用例缺少 input 字段: {case}"
            assert "expected" in case, f"用例缺少 expected 字段: {case}"
            assert isinstance(case["name"], str), "name 必须是字符串"
            assert isinstance(case["input"], str), "input 必须是字符串"
            assert isinstance(case["expected"], dict), "expected 必须是字典"

    def test_positive_case_keywords(self) -> None:
        """正面案例预期包含特定关键词。"""
        positive = EVAL_CASES[0]
        assert positive["name"].startswith("正面案例")
        expected = positive["expected"]
        assert "has_keywords" in expected, "正面案例应定义 has_keywords"
        assert len(expected["has_keywords"]) > 0, "has_keywords 不应为空"

    def test_negative_case_score_low(self) -> None:
        """负面案例预期分数较低。"""
        negative = EVAL_CASES[1]
        assert negative["name"].startswith("负面案例")
        score_range = negative["expected"]["score_range"]
        assert score_range[1] <= 0.5, "负面案例上限应 <= 0.5"

    def test_edge_case_no_crash(self) -> None:
        """边界案例定义 should_not_crash。"""
        edge = EVAL_CASES[2]
        assert edge["name"].startswith("边界案例")
        assert edge["expected"].get("should_not_crash") is True


# ═══════════════════════════════════════════════════════════════
#  LLM 分析测试
# ═══════════════════════════════════════════════════════════════

_ANALYZE_SYSTEM_PROMPT = (
    "你是一个技术资讯分析专家。请根据给定的仓库信息，"
    "生成一份结构化的中文分析报告。\n\n"
    "输出必须严格符合以下 JSON 格式（不要包含 markdown 代码块）：\n"
    '{"summary": "200-500字的中文摘要", '
    '"tags": ["标签1", "标签2", "标签3"], '
    '"category": "tool/framework/paper/library 之一", '
    '"score": 0.85}'
)


def _call_llm_analyze(input_text: str) -> Dict[str, Any]:
    """调用 LLM 分析输入文本。

    Args:
        input_text: 仓库信息文本。

    Returns:
        Dict[str, Any]: 解析后的 JSON 结果。
    """
    text, _usage = chat(
        prompt=input_text,
        system_prompt=_ANALYZE_SYSTEM_PROMPT,
        temperature=0.7,
    )
    import json

    # 尝试从 markdown 代码块中提取 JSON
    raw = text.strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        # 去掉首行的 ```json 和尾行的 ```
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        raw = "\n".join(lines).strip()

    result = json.loads(raw)
    return result


@pytest.mark.slow
class TestLLMAnalysis:
    """调用 LLM 的分析质量测试（标记为 slow，可跳过）。"""

    @pytest.mark.parametrize("case", EVAL_CASES, ids=lambda c: c["name"])
    def test_llm_analysis_quality(self, case: Dict[str, Any]) -> None:
        """LLM 分析结果符合预期范围。

        对每个 EVAL_CASE 调用 LLM，验证返回结果满足 expected 中的条件。
        """
        result = _call_llm_analyze(case["input"])
        expected = case["expected"]

        # 1. 分数范围断言
        if "score_range" in expected:
            score = float(result.get("score", 0))
            low, high = expected["score_range"]
            assert low <= score <= high, (
                f"[{case['name']}] 分数 {score} 不在范围 [{low}, {high}] 内"
            )

        # 2. 摘要长度断言
        summary = result.get("summary", "")
        if "summary_min_len" in expected:
            assert len(summary) >= expected["summary_min_len"], (
                f"[{case['name']}] 摘要长度 {len(summary)} < "
                f"{expected['summary_min_len']}"
            )
        if "summary_max_len" in expected:
            assert len(summary) <= expected["summary_max_len"], (
                f"[{case['name']}] 摘要长度 {len(summary)} > "
                f"{expected['summary_max_len']}"
            )

        # 3. 关键词包含断言
        if "has_keywords" in expected:
            for keyword in expected["has_keywords"]:
                assert keyword in summary, (
                    f"[{case['name']}] 摘要中未找到关键词 '{keyword}'"
                )

        # 4. 不应包含的关键词
        if "should_not_have" in expected:
            for keyword in expected["should_not_have"]:
                assert keyword not in summary, (
                    f"[{case['name']}] 摘要中不应出现 '{keyword}'"
                )

        logger.info("[%s] LLM 分析通过: score=%.2f", case["name"], result.get("score", 0))


# ═══════════════════════════════════════════════════════════════
#  LLM-as-Judge 测试
# ═══════════════════════════════════════════════════════════════

_JUDGE_SYSTEM_PROMPT = (
    "你是一个严格的内容质量评估专家。请对给定的技术资讯分析结果进行评分。\n\n"
    "评分标准（1-10 分）：\n"
    "- 10 分：摘要准确、全面、语言流畅，标签精准\n"
    "- 7-9 分：摘要较好，略有不足\n"
    "- 4-6 分：摘要基本可用，有明显问题\n"
    "- 1-3 分：摘要质量差，信息错误或缺失\n\n"
    "只输出一个 1-10 的整数分数，不要任何解释。"
)


@pytest.mark.slow
def test_llm_as_judge() -> None:
    """LLM-as-Judge：让 LLM 对分析结果打分，断言 >= 5。

    使用正面案例输入，让 LLM 分析后再让另一个 LLM（Judge）评分。
    """
    case = EVAL_CASES[0]  # 正面案例

    # 第一步：让 LLM 分析
    analysis = _call_llm_analyze(case["input"])
    summary = analysis.get("summary", "")
    tags = analysis.get("tags", [])

    # 第二步：让 Judge LLM 评分
    judge_prompt = (
        f"原始输入:\n{case['input']}\n\n"
        f"分析结果:\n"
        f"摘要: {summary}\n"
        f"标签: {', '.join(tags)}\n\n"
        f"请对这份分析结果的质量打分（1-10）："
    )

    score_text, _usage = chat(
        prompt=judge_prompt,
        system_prompt=_JUDGE_SYSTEM_PROMPT,
        temperature=0.1,
    )

    # 提取分数
    import re

    match = re.search(r"(\d+)", score_text)
    assert match is not None, f"Judge 未返回有效分数: {score_text}"
    score = int(match.group(1))

    assert 1 <= score <= 10, f"Judge 分数 {score} 不在 1-10 范围内"
    assert score >= 5, (
        f"Judge 评分 {score} < 5，分析质量不达标。\n"
        f"摘要: {summary[:100]}..."
    )

    logger.info("[LLM-as-Judge] 评分: %d/10", score)


# ═══════════════════════════════════════════════════════════════
#  本地逻辑测试（不调用 LLM）
# ═══════════════════════════════════════════════════════════════

def test_positive_case_mock_analysis() -> None:
    """模拟正面案例分析结果，验证断言逻辑。

    不调用 LLM，直接构造满足 expected 的结果，验证检查函数正确。
    """
    case = EVAL_CASES[0]
    expected = case["expected"]

    # 模拟 LLM 返回结果
    mock_result = {
        "summary": (
            "LangChain 是一个基于 Python 的流行框架，"
            "专注于大语言模型（LLM）应用开发。它支持链式调用、"
            "RAG（检索增强生成）和代理（Agent）模式，"
            "使开发者能快速构建复杂的 AI 应用。"
        ),
        "tags": ["框架", "LLM", "RAG", "代理"],
        "category": "framework",
        "score": 0.85,
    }

    # 验证摘要长度
    assert len(mock_result["summary"]) >= expected["summary_min_len"]

    # 验证关键词
    for keyword in expected["has_keywords"]:
        assert keyword in mock_result["summary"]

    # 验证分数范围
    low, high = expected["score_range"]
    assert low <= mock_result["score"] <= high


def test_negative_case_mock_analysis() -> None:
    """模拟负面案例分析结果，验证过滤逻辑。"""
    case = EVAL_CASES[1]
    expected = case["expected"]

    mock_result = {
        "summary": "这是一个关于烹饪的仓库，收集了家常菜做法。",
        "tags": ["烹饪", "食谱"],
        "category": "other",
        "score": 0.2,
    }

    # 验证分数较低
    low, high = expected["score_range"]
    assert low <= mock_result["score"] <= high

    # 验证不应包含的关键词
    for keyword in expected["should_not_have"]:
        assert keyword not in mock_result["summary"]

    # 验证摘要长度上限
    assert len(mock_result["summary"]) <= expected["summary_max_len"]


def test_edge_case_no_crash() -> None:
    """边界案例：验证极短输入不导致断言失败。"""
    case = EVAL_CASES[2]
    expected = case["expected"]

    # 模拟极简返回
    mock_result = {
        "summary": "AI 相关项目。",
        "tags": ["AI"],
        "category": "tool",
        "score": 0.3,
    }

    # 只要不崩溃就算通过
    assert expected["should_not_crash"] is True
    assert "score" in mock_result
    assert 0.0 <= mock_result["score"] <= 1.0
