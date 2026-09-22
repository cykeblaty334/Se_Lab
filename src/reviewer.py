# -*- coding: utf-8 -*-
"""业务层：错题与难题备忘录模块（极速复盘推荐）。

对应需求 FR-NOTE-01 / FR-NOTE-02：

1. **错题标记**：录入成绩时可打上 ``is_wrong`` 标签，也可事后补标；
2. **极速复盘推荐**：自动挑选 "最近做错最多、单题耗时最长、正确率最低"
   的若干考点，生成 "今日优先复盘清单"，并关联知识库中的公式 / 模板。

复盘优先级算法::

    优先级 = 3.0 × 错题条数
           + 2.0 × (1 - 正确率)
           + 1.5 × max(0, 单题耗时 / 目标耗时 - 1)

三个维度分别代表 "错得多"、"做得差"、"做得慢"，权重集中在
``config.REVIEW_*_WEIGHT`` 中，可根据备考阶段调整。
"""

from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

from . import config
from .database import Database
from .models import PracticeRecord, ReviewItem


def priority_score(
    wrong_records: int, accuracy: float, seconds_per_question: float
) -> float:
    """计算某考点的复盘优先级（越大越该优先复习）。"""
    slow_penalty = max(0.0, seconds_per_question / config.TARGET_SECONDS_PER_QUESTION - 1)
    score = (
        config.REVIEW_WRONG_WEIGHT * wrong_records
        + config.REVIEW_ACCURACY_WEIGHT * (1 - max(0.0, min(1.0, accuracy)))
        + config.REVIEW_SPEED_WEIGHT * slow_penalty
    )
    return round(score, 2)


def build_reason(
    wrong_records: int, accuracy: float, seconds_per_question: float
) -> str:
    """生成该考点被选入复盘清单的原因描述。"""
    parts: List[str] = []
    if wrong_records > 0:
        parts.append(f"错题 {wrong_records} 条")
    parts.append(f"正确率 {round(accuracy * 100, 1)}%")
    if seconds_per_question > config.SLOW_QUESTION_SECONDS:
        parts.append(f"单题 {round(seconds_per_question, 1)}s（偏慢）")
    elif seconds_per_question > config.TARGET_SECONDS_PER_QUESTION:
        parts.append(f"单题 {round(seconds_per_question, 1)}s（略慢）")
    return " · ".join(parts)


def is_worth_reviewing(
    wrong_records: int, accuracy: float, seconds_per_question: float
) -> bool:
    """判断考点是否值得纳入复盘清单。

    "错得多 / 做得差 / 做得慢" 三个维度全部正常的考点不占用清单名额，
    避免清单为了凑满条数而推荐已经掌握良好的考点。
    """
    return (
        wrong_records > 0
        or accuracy < config.REVIEW_ACCURACY_FLOOR
        or seconds_per_question > config.TARGET_SECONDS_PER_QUESTION
    )


class ReviewService:
    """复盘推荐服务。"""

    def __init__(self, db: Database) -> None:
        self.db = db

    # ---------------------------------------------------------- 复盘清单
    def _candidates(
        self, days: int, today: Optional[date]
    ) -> Tuple[int, List[ReviewItem]]:
        """返回 ``(窗口内有记录的考点数, 需要优先复盘的条目（已排序）)``。

        两个返回值分别对应 "清单为空" 的两种原因：窗口内根本没有数据，
        或者所有考点状态都正常，渲染时据此给出不同的提示。
        """
        base = today or date.today()
        start = (base - timedelta(days=days)).isoformat() if days else None
        rows = self.db.topic_aggregate(start, base.isoformat())

        items: List[ReviewItem] = []
        for row in rows:
            total = int(row["total_questions"] or 0)
            if total <= 0:
                continue
            correct = int(row["correct_questions"] or 0)
            duration = int(row["duration_seconds"] or 0)
            accuracy = correct / total
            per_question = duration / total
            wrong = int(row["wrong_records"] or 0)
            if not is_worth_reviewing(wrong, accuracy, per_question):
                continue
            topic_name = str(row["topic_name"])
            items.append(
                ReviewItem(
                    topic_id=int(row["topic_id"]),
                    topic_name=topic_name,
                    module_name=str(row["module_name"]),
                    records=int(row["records"]),
                    total_questions=total,
                    correct_questions=correct,
                    wrong_records=wrong,
                    duration_seconds=duration,
                    accuracy=round(accuracy, 4),
                    seconds_per_question=round(per_question, 2),
                    priority=priority_score(wrong, accuracy, per_question),
                    reason=build_reason(wrong, accuracy, per_question),
                    references=self.references_for(topic_name),
                )
            )

        items.sort(key=lambda item: (-item.priority, item.accuracy))
        return len(rows), items

    def review_items(
        self,
        days: int = config.REVIEW_RECENT_DAYS,
        top_n: int = config.REVIEW_TOP_N,
        today: Optional[date] = None,
    ) -> List[ReviewItem]:
        """返回按优先级排序的复盘清单（默认最近 30 天、最多 3 条）。"""
        return self._candidates(days, today)[1][: max(1, top_n)]

    def references_for(self, topic_name: str, limit: int = 2) -> List[str]:
        """检索与该考点相关的知识库条目（用于复盘时随时查阅公式/模板）。"""
        if not topic_name:
            return []
        hits = self.db.search_knowledge(topic_name, limit=limit)
        return [f"【{item.category}】{item.keyword}：{item.content}" for item in hits]

    # ---------------------------------------------------------- 错题标记
    def mark(self, record_id: int, is_wrong: bool = True) -> Optional[PracticeRecord]:
        """给指定记录打上 / 取消错题标签，返回更新后的记录。"""
        if not self.db.set_wrong_flag(record_id, is_wrong):
            return None
        return self.db.get_record(record_id)

    def wrong_records(self, limit: int = 10) -> List[PracticeRecord]:
        """返回最近的错题记录。"""
        return self.db.list_wrong_records(limit=limit)

    # ---------------------------------------------------------- 文本渲染
    def format_list(
        self,
        days: int = config.REVIEW_RECENT_DAYS,
        top_n: int = config.REVIEW_TOP_N,
        today: Optional[date] = None,
    ) -> str:
        """渲染 "今日优先复盘清单"。"""
        topic_count, items = self._candidates(days, today)
        items = items[: max(1, top_n)]
        wrong_count = self.db.count_wrong_records()
        scope = f"最近 {days} 天" if days else "全部记录"
        if not items:
            header = f"今日优先复盘清单（{scope}）\n" + "-" * 52 + "\n"
            if topic_count == 0:
                return header + (
                    "暂无带考点的练习记录，先在「成绩录入」时选择考点，"
                    "复盘清单才能定位到具体薄弱环节。"
                )
            return header + (
                f"{scope}内有记录的 {topic_count} 个考点均未触发复盘条件"
                "（无错题、正确率与做题节奏正常），今天可继续推进新内容。"
            )

        lines = [
            "=" * 52,
            f"今日优先复盘清单（{scope} · 累计错题 {wrong_count} 条）",
            "=" * 52,
        ]
        for index, item in enumerate(items, start=1):
            lines.append(
                f"{index}. 【{item.module_name} / {item.topic_name}】"
                f"优先级 {item.priority:g}"
            )
            lines.append(
                f"   题量 {item.correct_questions}/{item.total_questions}，"
                f"{item.reason}"
            )
            for reference in item.references:
                lines.append(f"   知识卡片：{reference}")
            lines.append("")
        lines.append("建议：先重做上述考点的错题，再用「python -m src.main quiz」抽测巩固。")

        weak = self.db.quiz_weak_keywords(limit=3)
        if weak:
            lines.append(
                "闪卡抽测薄弱点："
                + "、".join(
                    f"{row['keyword']}（{round(float(row['avg_score']), 1)} 分）" for row in weak
                )
            )
        lines.append("=" * 52)
        return "\n".join(lines)

    def as_dicts(
        self,
        days: int = config.REVIEW_RECENT_DAYS,
        top_n: int = config.REVIEW_TOP_N,
        today: Optional[date] = None,
    ) -> List[Dict[str, object]]:
        """把复盘清单转换为字典列表，供 Markdown 导出使用。"""
        return [
            {
                "topic_name": item.topic_name,
                "module_name": item.module_name,
                "priority": item.priority,
                "reason": item.reason,
                "accuracy": round(item.accuracy * 100, 1),
                "seconds_per_question": item.seconds_per_question,
                "wrong_records": item.wrong_records,
            }
            for item in self.review_items(days=days, top_n=top_n, today=today)
        ]
