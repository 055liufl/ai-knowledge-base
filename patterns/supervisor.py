"""Supervisor 监督模式：Worker + Supervisor 质量审核循环。

实现一个带质量控制的 LLM 任务处理流程：
1. Worker Agent 接收任务，输出 JSON 分析报告
2. Supervisor Agent 审核 Worker 输出，多维度评分
3. 审核不通过时带反馈重做，最多指定轮次
4. 超过轮次上限强制返回并附加警告

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

from workflows.model_client import chat

logger = logging.getLogger(__name__)

_WORKER_SYSTEM_PROMPT = (
    "你是一个专业的分析助手。请根据用户给定的任务，"
    "生成一份结构化的 JSON 分析报告。\n\n"
    "输出必须严格符合以下 JSON 格式（不要包含 markdown 代码块标记）：\n"
    "{\n"
    '  "analysis": "详细的分析内容",\n'
    '  "key_points": ["要点1", "要点2", "要点3"],\n'
    '  "conclusion": "总结性结论"\n'
    "}"
)

_SUPERVISOR_SYSTEM_PROMPT = (
    "你是一个严格的质量审核员。请对给定的分析报告进行多维度评分，"
    "并以 JSON 格式返回审核结果。\n\n"
    "评分维度（每项 1-10 分）：\n"
    "- accuracy: 准确性，事实是否正确、逻辑是否自洽\n"
    "- depth: 深度，分析是否深入、是否有洞察力\n"
    "- format: 格式，是否符合要求的 JSON 结构、字段是否完整\n"
    "\n"
    "综合得分 score 为三项的平均值（四舍五入取整）。\n"
    "通过标准：score >= 7。\n\n"
    "输出必须严格符合以下 JSON 格式（不要包含 markdown 代码块标记）：\n"
    "{\n"
    '  "passed": true/false,\n'
    '  "score": 综合得分(1-10),\n'
    '  "accuracy": 准确性得分(1-10),\n'
    '  "depth": 深度得分(1-10),\n'
    '  "format": 格式得分(1-10),\n'
    '  "feedback": "具体的改进建议，如果已通过可写无"\n'
    "}"
)


def _parse_json(text: str) -> dict[str, Any] | None:
    """从文本中提取并解析 JSON。

    先清理可能的 markdown 代码块，再尝试解析。

    Args:
        text: 包含 JSON 的原始文本。

    Returns:
        dict[str, Any] | None: 解析成功的字典，失败返回 None。
    """
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3].strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as exc:
        logger.warning("JSON 解析失败: %s, content=%s", exc, text[:200])
        return None


def _worker(task: str, feedback: str | None = None) -> dict[str, Any]:
    """Worker Agent：执行任务并生成 JSON 分析报告。

    如果提供了 feedback，Worker 会根据反馈改进输出。

    Args:
        task: 用户给定的任务描述。
        feedback: 上一次 Supervisor 的改进建议，首次调用为 None。

    Returns:
        dict[str, Any]: 解析后的分析报告字典，解析失败返回包含 error 的字典。
    """
    if feedback:
        prompt = (
            f"任务：{task}\n\n"
            f"上一次审核反馈（请据此改进）：{feedback}\n\n"
            "请生成改进后的 JSON 分析报告。"
        )
    else:
        prompt = f"任务：{task}\n\n请生成 JSON 分析报告。"

    try:
        text, usage = chat(
            prompt=prompt,
            system_prompt=_WORKER_SYSTEM_PROMPT,
            temperature=0.7,
        )
        logger.info(
            "Worker 完成: prompt_tokens=%d, completion_tokens=%d",
            usage.prompt_tokens,
            usage.completion_tokens,
        )
        result = _parse_json(text)
        if result is None:
            return {
                "error": "Worker 输出 JSON 解析失败",
                "raw": text,
            }
        return result
    except Exception as exc:
        logger.error("Worker 异常: %s", exc)
        return {"error": f"Worker 调用失败: {exc}"}


def _supervisor_review(output: dict[str, Any]) -> dict[str, Any]:
    """Supervisor Agent：审核 Worker 输出并评分。

    从准确性、深度、格式三个维度评分，输出 JSON 审核结果。

    Args:
        output: Worker 生成的分析报告字典。

    Returns:
        dict[str, Any]: 包含 passed、score、feedback 的审核结果字典。
    """
    output_text = json.dumps(output, ensure_ascii=False, indent=2)
    prompt = (
        "请对以下分析报告进行质量审核并评分：\n\n"
        f"{output_text}\n\n"
        "请返回 JSON 格式的审核结果。"
    )

    try:
        text, usage = chat(
            prompt=prompt,
            system_prompt=_SUPERVISOR_SYSTEM_PROMPT,
            temperature=0.3,
        )
        logger.info(
            "Supervisor 完成: prompt_tokens=%d, completion_tokens=%d",
            usage.prompt_tokens,
            usage.completion_tokens,
        )
        result = _parse_json(text)
        if result is None:
            return {
                "passed": False,
                "score": 0,
                "accuracy": 0,
                "depth": 0,
                "format": 0,
                "feedback": "Supervisor 输出 JSON 解析失败，默认不通过",
            }
        return result
    except Exception as exc:
        logger.error("Supervisor 异常: %s", exc)
        return {
            "passed": False,
            "score": 0,
            "accuracy": 0,
            "depth": 0,
            "format": 0,
            "feedback": f"Supervisor 调用失败: {exc}",
        }


def supervisor(task: str, max_retries: int = 3) -> dict[str, Any]:
    """Supervisor 监督模式入口。

    执行 Worker → Supervisor 审核循环，最多 max_retries 轮。
    通过(score >= 7)立即返回；不通过带反馈重做；
    超过轮次上限强制返回并附加警告。

    Args:
        task: 用户给定的任务描述。
        max_retries: 最大重做次数（包含首次，共 max_retries 轮）。
            默认 3 轮。

    Returns:
        dict[str, Any]: 包含以下字段的结果字典：
            - output: Worker 最终输出的分析报告
            - attempts: 实际尝试次数
            - final_score: 最终审核得分
            - warning: 如果超过轮次上限，包含警告信息；否则为 None
            - review: 最后一次 Supervisor 的完整审核结果

    Example:
        >>> result = supervisor("分析 Python 的 GIL 机制")
        >>> print(result["output"]["conclusion"])
    """
    if not task or not task.strip():
        return {
            "output": {},
            "attempts": 0,
            "final_score": 0,
            "warning": "任务为空，无法执行",
            "review": {},
        }

    task = task.strip()
    logger.info("Supervisor 开始: task=%s, max_retries=%d", task, max_retries)

    output: dict[str, Any] = {}
    review: dict[str, Any] = {}
    feedback: str | None = None
    attempts = 0

    for attempt in range(1, max_retries + 1):
        attempts = attempt
        logger.info("第 %d/%d 轮尝试", attempt, max_retries)

        # Worker 生成报告
        output = _worker(task, feedback)
        if "error" in output:
            logger.error("Worker 输出错误: %s", output["error"])
            review = {
                "passed": False,
                "score": 0,
                "feedback": f"Worker 错误: {output['error']}",
            }
            break

        # Supervisor 审核
        review = _supervisor_review(output)
        score = review.get("score", 0)
        passed = review.get("passed", False)

        logger.info(
            "第 %d 轮审核: passed=%s, score=%d, "
            "accuracy=%s, depth=%s, format=%s",
            attempt,
            passed,
            score,
            review.get("accuracy", "N/A"),
            review.get("depth", "N/A"),
            review.get("format", "N/A"),
        )

        if passed and score >= 7:
            logger.info("审核通过，返回结果")
            return {
                "output": output,
                "attempts": attempts,
                "final_score": score,
                "warning": None,
                "review": review,
            }

        # 未通过，准备下一轮反馈
        feedback = review.get("feedback", "请改进输出质量")
        logger.info("审核未通过，反馈: %s", feedback)

    # 超过轮次上限，强制返回
    warning = (
        f"已达到最大重试次数（{max_retries} 轮），"
        f"最终得分 {review.get('score', 0)} 未达通过标准（>=7）。"
        "强制返回当前最优结果。"
    )
    logger.warning(warning)

    return {
        "output": output,
        "attempts": attempts,
        "final_score": review.get("score", 0),
        "warning": warning,
        "review": review,
    }


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    test_tasks = [
        "分析 Python 的 GIL 机制及其对多线程的影响",
        "解释 Transformer 架构中的自注意力机制",
        "",  # 边界测试：空任务
    ]

    print("=" * 60)
    print("Supervisor 监督模式测试")
    print("=" * 60)

    for task in test_tasks:
        print(f"\n{'─' * 60}")
        print(f"任务: {task!r}")
        print(f"{'─' * 60}")

        try:
            result = supervisor(task, max_retries=2)
            print(f"尝试次数: {result['attempts']}")
            print(f"最终得分: {result['final_score']}")
            if result.get("warning"):
                print(f"警告: {result['warning']}")
            print(f"审核结果: passed={result['review'].get('passed')}, "
                  f"score={result['review'].get('score')}, "
                  f"accuracy={result['review'].get('accuracy')}, "
                  f"depth={result['review'].get('depth')}, "
                  f"format={result['review'].get('format')}")
            print(f"Worker 输出:\n{json.dumps(result['output'], ensure_ascii=False, indent=2)}")
        except Exception as exc:
            print(f"异常: {exc}")

    print(f"\n{'=' * 60}")
    print("测试结束")
    print("=" * 60)
