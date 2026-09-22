# -*- coding: utf-8 -*-
"""领域数据模型模块。

用 dataclass 描述系统核心实体，并提供从数据库行到对象的转换方法，
使业务层无需直接操作 sqlite3.Row，降低层与层之间的耦合。
"""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Module:
    """行测模块（言语、判断、数量、资料、常识）。"""

    id: Optional[int]
    code: str
    name: str
    weight: float = 0.0

    @classmethod
    def from_row(cls, row) -> "Module":
        return cls(id=row["id"], code=row["code"], name=row["name"], weight=row["weight"])


@dataclass
class Topic:
    """模块下的细分考点，例如资料分析 -> 隔年增长率。"""

    id: Optional[int]
    module_id: int
    name: str
    difficulty: float = 0.5

    @classmethod
    def from_row(cls, row) -> "Topic":
        return cls(
            id=row["id"],
            module_id=row["module_id"],
            name=row["name"],
            difficulty=row["difficulty"],
        )


@dataclass
class PracticeRecord:
    """一次练习记录（核心数据实体）。"""

    id: Optional[int]
    record_date: str
    module_id: int
    topic_id: Optional[int]
    total_questions: int
    correct_questions: int
    duration_seconds: int
    note: str = ""
    created_at: str = ""
    is_wrong: bool = False
    module_name: str = ""
    topic_name: str = ""

    # ---------------------------------------------------------- 派生指标
    @property
    def accuracy(self) -> float:
        """正确率，取值 0~1；总题数为 0 时返回 0 以避免除零。"""
        if self.total_questions <= 0:
            return 0.0
        return self.correct_questions / self.total_questions

    @property
    def seconds_per_question(self) -> float:
        """单题平均耗时（秒）。"""
        if self.total_questions <= 0:
            return 0.0
        return self.duration_seconds / self.total_questions

    @classmethod
    def from_row(cls, row) -> "PracticeRecord":
        keys = row.keys()
        return cls(
            id=row["id"],
            record_date=row["record_date"],
            module_id=row["module_id"],
            topic_id=row["topic_id"],
            total_questions=row["total_questions"],
            correct_questions=row["correct_questions"],
            duration_seconds=row["duration_seconds"],
            note=row["note"] or "",
            created_at=row["created_at"],
            is_wrong=bool(row["is_wrong"]) if "is_wrong" in keys else False,
            module_name=row["module_name"] if "module_name" in keys else "",
            topic_name=(row["topic_name"] or "") if "topic_name" in keys else "",
        )


@dataclass
class Announcement:
    """招考公告实体。"""

    id: Optional[int]
    source: str
    title: str
    url: str
    publish_date: Optional[str] = None
    matched_keyword: str = ""
    fetched_at: str = ""

    @classmethod
    def from_row(cls, row) -> "Announcement":
        return cls(
            id=row["id"],
            source=row["source"],
            title=row["title"],
            url=row["url"],
            publish_date=row["publish_date"],
            matched_keyword=row["matched_keyword"] or "",
            fetched_at=row["fetched_at"],
        )


@dataclass
class KnowledgeItem:
    """知识库条目（公式 / 解题技巧 / 申论模板）。"""

    id: Optional[int]
    keyword: str
    category: str
    content: str
    example: str = ""

    @classmethod
    def from_row(cls, row) -> "KnowledgeItem":
        return cls(
            id=row["id"],
            keyword=row["keyword"],
            category=row["category"],
            content=row["content"],
            example=row["example"] or "",
        )


@dataclass
class ModuleDiagnosis:
    """单个模块的诊断结果。"""

    module_id: int
    module_name: str
    records: int = 0
    total_questions: int = 0
    correct_questions: int = 0
    duration_seconds: int = 0
    accuracy: float = 0.0
    seconds_per_question: float = 0.0
    efficiency_score: float = 0.0
    stability_score: float = 0.0
    accuracy_std: float = 0.0
    final_score: float = 0.0
    is_weak: bool = False
    weak_topics: List[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "module_id": self.module_id,
            "module_name": self.module_name,
            "records": self.records,
            "total_questions": self.total_questions,
            "correct_questions": self.correct_questions,
            "accuracy": self.accuracy,
            "seconds_per_question": self.seconds_per_question,
            "efficiency_score": self.efficiency_score,
            "stability_score": self.stability_score,
            "accuracy_std": self.accuracy_std,
            "final_score": self.final_score,
            "is_weak": self.is_weak,
            "weak_topics": list(self.weak_topics),
        }


@dataclass
class ReviewItem:
    """复盘清单条目：一个待优先复习的考点。"""

    topic_id: Optional[int]
    topic_name: str
    module_name: str
    records: int = 0
    total_questions: int = 0
    correct_questions: int = 0
    wrong_records: int = 0
    duration_seconds: int = 0
    accuracy: float = 0.0
    seconds_per_question: float = 0.0
    priority: float = 0.0
    reason: str = ""
    references: List[str] = field(default_factory=list)


@dataclass
class QuizQuestion:
    """闪卡抽测题目：由知识库条目生成。"""

    item_id: Optional[int]
    keyword: str
    category: str
    question: str
    expected: str
    example: str = ""


@dataclass
class QuizResult:
    """一次闪卡作答复盘结果。"""

    question: QuizQuestion
    answer: str
    score: float = 0.0
    passed: bool = False
    level: str = ""
    hit_fragments: List[str] = field(default_factory=list)
    missed_fragments: List[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "keyword": self.question.keyword,
            "category": self.question.category,
            "answer": self.answer,
            "score": self.score,
            "passed": self.passed,
            "level": self.level,
        }
