# -*- coding: utf-8 -*-
"""业务层：弱项诊断模块。

对应需求 FR-ANA-01 / FR-ANA-02，把原始练习记录转化为可执行的复习建议。
诊断模型由三个维度加权构成：

    综合得分 = 0.6 × 正确率分 + 0.3 × 效率分 + 0.1 × 稳定性分

* 正确率分：模块加权正确率（0~100）；
* 效率分  ：目标单题耗时 / 实际单题耗时，上限 100 分；
* 稳定性分：1 - 正确率标准差 / 0.2，反映成绩波动，越稳定分越高。

综合得分低于 ``WEAK_SCORE_THRESHOLD`` 的模块被判为弱项，并进一步
下钻到考点粒度，找出正确率最低的具体考点。
"""

import statistics
from typing import Dict, List, Optional, Tuple

from . import config
from .database import Database
from .models import ModuleDiagnosis


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    """把数值限制在 [low, high] 区间内。"""
    return max(low, min(high, value))


def accuracy_score(correct: int, total: int) -> float:
    """正确率分（0~1）。"""
    if total <= 0:
        return 0.0
    return _clamp(correct / total)


def efficiency_score(seconds_per_question: float) -> float:
    """效率分（0~1）：以 45 秒/题为满分基准，越慢分越低。"""
    if seconds_per_question <= 0:
        return 1.0
    return _clamp(config.TARGET_SECONDS_PER_QUESTION / seconds_per_question)


def stability_score(accuracy_list: List[float]) -> Tuple[float, float]:
    """稳定性分与正确率标准差。

    :param accuracy_list: 每次练习的正确率序列（0~1）。
    :return: (稳定性分 0~1, 标准差)
    """
    if len(accuracy_list) < 2:
        return 1.0, 0.0
    std = statistics.pstdev(accuracy_list)
    return _clamp(1.0 - std / 0.2), std


def compute_score(acc: float, eff: float, stab: float) -> float:
    """按配置权重合成综合得分（百分制）。"""
    total = (
        config.WEIGHT_ACCURACY * acc
        + config.WEIGHT_EFFICIENCY * eff
        + config.WEIGHT_STABILITY * stab
    )
    return round(total * 100, 2)


class Analyzer:
    """弱项诊断分析器。"""

    def __init__(self, db: Database) -> None:
        self.db = db

    # ------------------------------------------------------------ 模块诊断
    def diagnose_modules(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        min_records: int = 1,
    ) -> List[ModuleDiagnosis]:
        """按模块生成诊断结果（按综合得分升序，弱项排在最前）。"""
        aggregates = self.db.module_aggregate(start_date, end_date)
        weak_topics_map = self._weak_topics_by_module(start_date, end_date)

        results: List[ModuleDiagnosis] = []
        for row in aggregates:
            records = int(row["records"])
            total = int(row["total_questions"])
            correct = int(row["correct_questions"])
            duration = int(row["duration_seconds"])

            if records == 0:
                # 尚未练习的模块不参与评分：若按 0 正确率 + 满分效率计算，
                # 会得到 40 分的 "虚假中评"，导致其排名反而优于真实弱项。
                diagnosis = ModuleDiagnosis(
                    module_id=int(row["module_id"]),
                    module_name=str(row["module_name"]),
                )
                results.append(diagnosis)
                continue

            acc = accuracy_score(correct, total)
            per_question = duration / total if total else 0.0
            eff = efficiency_score(per_question)
            accuracies = self._record_accuracies(int(row["module_id"]), start_date, end_date)
            stab, std = stability_score(accuracies)
            final = compute_score(acc, eff, stab)

            diagnosis = ModuleDiagnosis(
                module_id=int(row["module_id"]),
                module_name=str(row["module_name"]),
                records=records,
                total_questions=total,
                correct_questions=correct,
                duration_seconds=duration,
                accuracy=round(acc, 4),
                seconds_per_question=round(per_question, 2),
                efficiency_score=round(eff, 4),
                stability_score=round(stab, 4),
                accuracy_std=round(std, 4),
                final_score=final,
                is_weak=records >= min_records and final < config.WEAK_SCORE_THRESHOLD,
                weak_topics=weak_topics_map.get(int(row["module_id"]), []),
            )
            results.append(diagnosis)

        # 已练习模块按得分升序（弱项在前）；未练习模块统一排在末尾
        results.sort(key=lambda item: (item.records == 0, item.final_score))
        return results

    def _record_accuracies(
        self,
        module_id: int,
        start_date: Optional[str],
        end_date: Optional[str],
    ) -> List[float]:
        """取某模块每次练习的正确率序列，用于计算波动。"""
        records = self.db.list_records(
            module_id=module_id, start_date=start_date, end_date=end_date
        )
        return [record.accuracy for record in records if record.total_questions > 0]

    def _weak_topics_by_module(
        self,
        start_date: Optional[str],
        end_date: Optional[str],
        threshold: float = 0.6,
    ) -> Dict[int, List[str]]:
        """找出各模块中正确率低于阈值的考点。"""
        mapping: Dict[int, List[str]] = {}
        for row in self.db.topic_aggregate(start_date, end_date):
            total = int(row["total_questions"])
            if total <= 0:
                continue
            acc = int(row["correct_questions"]) / total
            if acc >= threshold:
                continue
            module_name = str(row["module_name"])
            module = self.db.get_module_by_name(module_name)
            if module is None or module.id is None:
                continue
            mapping.setdefault(module.id, []).append(
                f"{row['topic_name']}（{round(acc * 100, 1)}%）"
            )
        return mapping

    # ------------------------------------------------------------ 趋势分析
    def trend(
        self, days: int = 30, module_id: Optional[int] = None
    ) -> List[Tuple[str, float, float]]:
        """返回按日聚合的趋势序列 ``[(日期, 正确率%, 单题耗时), ...]``。"""
        series = []
        for row in self.db.daily_aggregate(days=days, module_id=module_id):
            total = int(row["total_questions"] or 0)
            if total <= 0:
                continue
            accuracy = int(row["correct_questions"]) / total * 100
            per_question = int(row["duration_seconds"]) / total
            series.append((str(row["record_date"]), round(accuracy, 2), round(per_question, 2)))
        return series

    def slow_modules(self, threshold_seconds: Optional[float] = None) -> List[ModuleDiagnosis]:
        """返回单题平均耗时超过阈值的模块（FR-ANA-02 的效率异常清单）。"""
        limit = threshold_seconds or config.SLOW_QUESTION_SECONDS
        return [
            item
            for item in self.diagnose_modules()
            if item.total_questions > 0 and item.seconds_per_question > limit
        ]

    # ------------------------------------------------------------ 汇总
    def overall(self, start_date: Optional[str] = None, end_date: Optional[str] = None) -> Dict:
        """返回整体统计概览。"""
        aggregates = self.db.module_aggregate(start_date, end_date)
        total = sum(int(row["total_questions"]) for row in aggregates)
        correct = sum(int(row["correct_questions"]) for row in aggregates)
        duration = sum(int(row["duration_seconds"]) for row in aggregates)
        records = sum(int(row["records"]) for row in aggregates)
        covered = sum(1 for row in aggregates if int(row["records"]) > 0)
        return {
            "records": records,
            "covered_modules": covered,
            "total_modules": len(aggregates),
            "total_questions": total,
            "correct_questions": correct,
            "duration_seconds": duration,
            "accuracy": round(correct / total * 100, 2) if total else 0.0,
            "seconds_per_question": round(duration / total, 2) if total else 0.0,
        }

    def ready_for_radar(self) -> bool:
        """是否满足生成雷达图的最小数据量要求。"""
        return self.db.count_records() >= config.MIN_RECORDS_FOR_RADAR

    # ------------------------------------------------------------ 文本报告
    def text_report(self, start_date: Optional[str] = None, end_date: Optional[str] = None) -> str:
        """生成命令行文本诊断报告。"""
        overall = self.overall(start_date, end_date)
        if overall["records"] == 0:
            return "暂无练习记录，请先使用「成绩录入」功能。"

        lines = [
            "=" * 60,
            "CEATS 弱项诊断报告",
            "-" * 60,
            f"练习记录  : {overall['records']} 条"
            f"（覆盖 {overall['covered_modules']}/{overall['total_modules']} 个模块）",
            f"累计题量  : {overall['total_questions']} 题，"
            f"答对 {overall['correct_questions']} 题",
            f"整体正确率: {overall['accuracy']}%",
            f"平均单题耗时: {overall['seconds_per_question']}s",
            "-" * 60,
            f"{'模块':<12}{'正确率':>8}{'单题耗时':>10}{'综合得分':>10}{'判定':>8}",
        ]
        for item in self.diagnose_modules(start_date, end_date):
            if item.records == 0:
                continue
            flag = "弱项" if item.is_weak else "正常"
            lines.append(
                f"{item.module_name:<12}{item.accuracy * 100:>7.1f}%"
                f"{item.seconds_per_question:>9.1f}s{item.final_score:>10.1f}{flag:>8}"
            )

        weak = [item for item in self.diagnose_modules(start_date, end_date) if item.is_weak]
        lines.append("-" * 60)
        if weak:
            lines.append("薄弱环节定位：")
            for item in weak:
                detail = "、".join(item.weak_topics) if item.weak_topics else "暂无细分考点数据"
                lines.append(f"  · {item.module_name}：{detail}")
        else:
            lines.append("暂未发现明显弱项，继续保持当前复习节奏。")

        slow = self.slow_modules()
        if slow:
            lines.append("-" * 60)
            lines.append(
                f"效率预警（单题耗时 > {int(config.SLOW_QUESTION_SECONDS)}s）："
                + "、".join(f"{item.module_name}({item.seconds_per_question}s)" for item in slow)
            )

        unstarted = [
            item.module_name
            for item in self.diagnose_modules(start_date, end_date)
            if item.records == 0
        ]
        if unstarted:
            lines.append("-" * 60)
            lines.append("尚未开始练习：" + "、".join(unstarted) + "（未参与评分）")
        lines.append("=" * 60)
        return "\n".join(lines)
