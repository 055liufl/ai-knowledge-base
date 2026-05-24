"""多 Agent 预算守卫模块。

实现 CostGuard 类，提供 LLM 调用成本的实时监控、预算预警和超限保护。

编码规范：
    - 严格遵循 PEP 8
    - 使用 Google 风格 docstring
    - 使用 logging 而非 print
"""

from __future__ import annotations

import json
import logging
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 异常定义
# ---------------------------------------------------------------------------
class BudgetExceededError(Exception):
    """预算超限异常。

    当累计成本超过预算时由 CostGuard.check() 抛出。
    """

    def __init__(self, total_cost: float, budget: float, message: str = "") -> None:
        """初始化异常。

        Args:
            total_cost: 当前累计成本。
            budget: 预算上限。
            message: 附加信息。
        """
        self.total_cost = total_cost
        self.budget = budget
        super().__init__(
            f"预算超限: 已使用 {total_cost:.4f} 元 / 预算 {budget:.4f} 元。{message}"
        )


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------
@dataclass
class CostRecord:
    """单次 LLM 调用成本记录。

    Attributes:
        timestamp: 调用时间戳（ISO 8601 格式）。
        node_name: 调用来源节点名称。
        prompt_tokens: 输入 Token 数。
        completion_tokens: 输出 Token 数。
        cost_yuan: 本次调用成本（人民币元）。
        model: 使用的模型名称。
    """

    timestamp: str
    node_name: str
    prompt_tokens: int
    completion_tokens: int
    cost_yuan: float
    model: str = ""


# ---------------------------------------------------------------------------
# CostGuard 预算守卫
# ---------------------------------------------------------------------------
class CostGuard:
    """多 Agent 预算守卫。

    提供三重保护机制：
        1. record: 记录每次 LLM 调用的成本
        2. check: 检查预算状态，超限时抛出异常
        3. get_report/save_report: 生成并保存成本报告

    Attributes:
        budget_yuan: 预算上限（人民币元）。
        alert_threshold: 预警阈值（0.0-1.0），默认 0.8。
        input_price_per_million: 输入 Token 单价（元/百万 token）。
        output_price_per_million: 输出 Token 单价（元/百万 token）。
    """

    def __init__(
        self,
        budget_yuan: float = 1.0,
        alert_threshold: float = 0.8,
        input_price_per_million: float = 1.0,
        output_price_per_million: float = 2.0,
    ) -> None:
        """初始化 CostGuard。

        Args:
            budget_yuan: 预算上限（人民币元），默认 1.0。
            alert_threshold: 预警阈值（0.0-1.0），默认 0.8。
            input_price_per_million: 输入 Token 单价（元/百万 token），默认 1.0。
            output_price_per_million: 输出 Token 单价（元/百万 token），默认 2.0。
        """
        self.budget_yuan = max(budget_yuan, 0.0)
        self.alert_threshold = max(min(alert_threshold, 1.0), 0.0)
        self.input_price_per_million = max(input_price_per_million, 0.0)
        self.output_price_per_million = max(output_price_per_million, 0.0)

        self._records: List[CostRecord] = []
        self._total_prompt_tokens = 0
        self._total_completion_tokens = 0
        self._total_cost_yuan = 0.0

        logger.info(
            "[CostGuard] 初始化完成: budget=%.4f, alert_threshold=%.1f, "
            "input_price=%.2f/百万, output_price=%.2f/百万",
            self.budget_yuan,
            self.alert_threshold,
            self.input_price_per_million,
            self.output_price_per_million,
        )

    # ── 核心方法：record ─────────────────────────────────────
    def record(
        self,
        node_name: str,
        usage: Dict[str, int],
        model: str = "",
    ) -> CostRecord:
        """记录一次 LLM 调用的成本。

        Args:
            node_name: 调用来源节点名称。
            usage: Token 用量字典，必须包含 prompt_tokens 和 completion_tokens。
            model: 使用的模型名称，默认空字符串。

        Returns:
            CostRecord: 本次调用的成本记录。
        """
        prompt_tokens = int(usage.get("prompt_tokens", 0))
        completion_tokens = int(usage.get("completion_tokens", 0))

        # 计算成本（元）
        input_cost = prompt_tokens * self.input_price_per_million / 1_000_000
        output_cost = completion_tokens * self.output_price_per_million / 1_000_000
        cost_yuan = input_cost + output_cost

        record = CostRecord(
            timestamp=datetime.now(timezone.utc).isoformat(),
            node_name=node_name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_yuan=cost_yuan,
            model=model,
        )

        self._records.append(record)
        self._total_prompt_tokens += prompt_tokens
        self._total_completion_tokens += completion_tokens
        self._total_cost_yuan += cost_yuan

        logger.info(
            "[CostGuard] 记录成本: node=%s, prompt=%d, completion=%d, "
            "cost=%.6f, total_cost=%.6f",
            node_name,
            prompt_tokens,
            completion_tokens,
            cost_yuan,
            self._total_cost_yuan,
        )

        return record

    # ── 核心方法：check ──────────────────────────────────────
    def check(self) -> Dict[str, Any]:
        """检查预算状态。

        返回当前预算使用状态。如果超出预算，抛出 BudgetExceededError。
        如果接近预算（>= alert_threshold），返回 warning 状态。

        Returns:
            Dict[str, Any]: 预算状态字典，包含：
                - status: "ok" / "warning" / "exceeded"
                - total_cost: 累计成本
                - budget: 预算上限
                - usage_ratio: 使用比例（0.0-1.0+）
                - message: 状态说明

        Raises:
            BudgetExceededError: 累计成本超过预算时抛出。
        """
        total_cost = self._total_cost_yuan
        budget = self.budget_yuan
        usage_ratio = total_cost / budget if budget > 0 else 0.0

        if total_cost > budget:
            message = (
                f"预算已超限: 已使用 {total_cost:.4f} 元 / "
                f"预算 {budget:.4f} 元 (使用率 {usage_ratio:.1%})"
            )
            logger.error("[CostGuard] %s", message)
            raise BudgetExceededError(total_cost, budget, message)

        if usage_ratio >= self.alert_threshold:
            message = (
                f"预算预警: 已使用 {total_cost:.4f} 元 / "
                f"预算 {budget:.4f} 元 (使用率 {usage_ratio:.1%})"
            )
            logger.warning("[CostGuard] %s", message)
            return {
                "status": "warning",
                "total_cost": round(total_cost, 6),
                "budget": budget,
                "usage_ratio": round(usage_ratio, 4),
                "message": message,
            }

        message = (
            f"预算正常: 已使用 {total_cost:.4f} 元 / "
            f"预算 {budget:.4f} 元 (使用率 {usage_ratio:.1%})"
        )
        logger.info("[CostGuard] %s", message)
        return {
            "status": "ok",
            "total_cost": round(total_cost, 6),
            "budget": budget,
            "usage_ratio": round(usage_ratio, 4),
            "message": message,
        }

    # ── 核心方法：get_report ─────────────────────────────────
    def get_report(self) -> Dict[str, Any]:
        """生成成本报告。

        按节点分组统计成本、Token 用量和调用次数。

        Returns:
            Dict[str, Any]: 成本报告字典，包含：
                - summary: 总体统计
                - by_node: 按节点分组的详细统计
                - records: 完整记录列表
        """
        by_node: Dict[str, Dict[str, Any]] = {}
        for record in self._records:
            node = record.node_name
            if node not in by_node:
                by_node[node] = {
                    "call_count": 0,
                    "total_prompt_tokens": 0,
                    "total_completion_tokens": 0,
                    "total_cost_yuan": 0.0,
                    "models": set(),
                }
            by_node[node]["call_count"] += 1
            by_node[node]["total_prompt_tokens"] += record.prompt_tokens
            by_node[node]["total_completion_tokens"] += record.completion_tokens
            by_node[node]["total_cost_yuan"] += record.cost_yuan
            if record.model:
                by_node[node]["models"].add(record.model)

        # 将 set 转为 list（JSON 可序列化）
        for node in by_node:
            by_node[node]["models"] = list(by_node[node]["models"])
            by_node[node]["total_cost_yuan"] = round(
                by_node[node]["total_cost_yuan"], 6
            )

        report = {
            "summary": {
                "total_records": len(self._records),
                "total_prompt_tokens": self._total_prompt_tokens,
                "total_completion_tokens": self._total_completion_tokens,
                "total_cost_yuan": round(self._total_cost_yuan, 6),
                "budget_yuan": self.budget_yuan,
                "usage_ratio": round(
                    self._total_cost_yuan / self.budget_yuan
                    if self.budget_yuan > 0
                    else 0.0,
                    4,
                ),
            },
            "by_node": by_node,
            "records": [
                {
                    "timestamp": r.timestamp,
                    "node_name": r.node_name,
                    "prompt_tokens": r.prompt_tokens,
                    "completion_tokens": r.completion_tokens,
                    "cost_yuan": round(r.cost_yuan, 6),
                    "model": r.model,
                }
                for r in self._records
            ],
        }

        logger.info(
            "[CostGuard] 生成报告: %d 条记录, 总成本 %.6f 元",
            len(self._records),
            self._total_cost_yuan,
        )
        return report

    # ── 核心方法：save_report ────────────────────────────────
    def save_report(self, path: str | None = None) -> Path:
        """保存成本报告到 JSON 文件。

        Args:
            path: 保存路径。None 时自动生成文件名。

        Returns:
            Path: 保存的文件路径。
        """
        if path is None:
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            path = f"cost_report_{timestamp}.json"

        file_path = Path(path)
        report = self.get_report()

        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

        logger.info("[CostGuard] 报告已保存: %s", file_path.absolute())
        return file_path


# ---------------------------------------------------------------------------
# 本地测试
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stdout,
    )

    print("=" * 60)
    print("CostGuard 预算守卫测试")
    print("=" * 60)

    # ── 测试 1: 成本追踪正确 ─────────────────────────────────
    print("\n--- 测试 1: 成本追踪正确 ---")
    guard = CostGuard(
        budget_yuan=1.0,
        alert_threshold=0.8,
        input_price_per_million=1.0,
        output_price_per_million=2.0,
    )

    # 记录 2 次调用
    guard.record(
        node_name="analyze_node",
        usage={"prompt_tokens": 1000, "completion_tokens": 500},
        model="deepseek-chat",
    )
    guard.record(
        node_name="review_node",
        usage={"prompt_tokens": 2000, "completion_tokens": 1000},
        model="deepseek-chat",
    )

    # 验证累计值
    expected_prompt = 3000
    expected_completion = 1500
    expected_cost = (
        expected_prompt * 1.0 / 1_000_000
        + expected_completion * 2.0 / 1_000_000
    )

    assert guard._total_prompt_tokens == expected_prompt, (
        f"prompt_tokens 不匹配: {guard._total_prompt_tokens} != {expected_prompt}"
    )
    assert guard._total_completion_tokens == expected_completion, (
        f"completion_tokens 不匹配: {guard._total_completion_tokens} != {expected_completion}"
    )
    assert abs(guard._total_cost_yuan - expected_cost) < 1e-9, (
        f"cost 不匹配: {guard._total_cost_yuan} != {expected_cost}"
    )

    print(f"  总 prompt_tokens: {guard._total_prompt_tokens} ✓")
    print(f"  总 completion_tokens: {guard._total_completion_tokens} ✓")
    print(f"  总 cost_yuan: {guard._total_cost_yuan:.6f} ✓")

    # ── 测试 2: 预算超限检测 ─────────────────────────────────
    print("\n--- 测试 2: 预算超限检测 ---")
    guard_small = CostGuard(
        budget_yuan=0.001,  # 很小的预算
        input_price_per_million=1.0,
        output_price_per_million=2.0,
    )

    # 记录一次调用就超限
    guard_small.record(
        node_name="test_node",
        usage={"prompt_tokens": 1000, "completion_tokens": 1000},
    )

    try:
        guard_small.check()
        assert False, "应该抛出 BudgetExceededError"
    except BudgetExceededError as exc:
        print(f"  正确捕获 BudgetExceededError: {exc} ✓")

    # ── 测试 3: 预警阈值触发 ─────────────────────────────────
    print("\n--- 测试 3: 预警阈值触发 ---")
    guard_alert = CostGuard(
        budget_yuan=1.0,
        alert_threshold=0.5,  # 50% 就预警
        input_price_per_million=1.0,
        output_price_per_million=2.0,
    )

    # 记录一次调用，使用率约 60%（触发预警）
    guard_alert.record(
        node_name="analyze_node",
        usage={"prompt_tokens": 400_000, "completion_tokens": 100_000},
    )

    result = guard_alert.check()
    assert result["status"] == "warning", (
        f"预期 warning，实际 {result['status']}"
    )
    assert result["usage_ratio"] >= 0.5, (
        f"usage_ratio 应 >= 0.5，实际 {result['usage_ratio']}"
    )
    print(f"  status={result['status']} ✓")
    print(f"  usage_ratio={result['usage_ratio']:.2%} ✓")
    print(f"  message={result['message']} ✓")

    # ── 测试 4: get_report ───────────────────────────────────
    print("\n--- 测试 4: 成本报告 ---")
    report = guard.get_report()
    assert report["summary"]["total_records"] == 2
    assert "analyze_node" in report["by_node"]
    assert "review_node" in report["by_node"]
    assert report["by_node"]["analyze_node"]["call_count"] == 1
    assert report["by_node"]["review_node"]["call_count"] == 1
    print(f"  总记录数: {report['summary']['total_records']} ✓")
    print(f"  analyze_node 调用次数: {report['by_node']['analyze_node']['call_count']} ✓")
    print(f"  review_node 调用次数: {report['by_node']['review_node']['call_count']} ✓")

    # ── 测试 5: save_report ──────────────────────────────────
    print("\n--- 测试 5: 保存报告 ---")
    report_path = guard.save_report("/tmp/cost_guard_test_report.json")
    assert report_path.exists(), "报告文件未创建"
    with open(report_path, "r", encoding="utf-8") as f:
        loaded = json.load(f)
    assert loaded["summary"]["total_records"] == 2
    print(f"  报告已保存: {report_path} ✓")

    print("\n" + "=" * 60)
    print("所有测试通过")
    print("=" * 60)
