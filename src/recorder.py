# -*- coding: utf-8 -*-
"""业务层：成绩录入模块。

对应需求 FR-REC-01 / FR-REC-02，负责：
1. 校验用户输入（题数、对题数、用时、日期、模块、考点）；
2. 将一次练习转换为 ``PracticeRecord`` 并写入数据库；
3. 计算正确率与单题平均耗时，返回可读的即时反馈。

设计原则：所有校验集中在 ``parse_*`` 系列纯函数中，便于单元测试，
服务类 ``RecordService`` 只负责编排流程。
"""

import re
from datetime import date, timedelta
from typing import List, Optional

from . import config
from .database import Database
from .models import Module, PracticeRecord, Topic

#: 允许的日期分隔符写法，如 2026-09-21 / 2026/9/21 / 09-21
_DATE_PATTERN = re.compile(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})$")
_SHORT_DATE_PATTERN = re.compile(r"^(\d{1,2})[-/.](\d{1,2})$")
#: 用时格式：纯秒数，或 mm:ss / hh:mm:ss
_DURATION_COLON = re.compile(r"^(\d{1,2}):([0-5]?\d)(?::([0-5]?\d))?$")


class RecordError(ValueError):
    """录入数据非法时抛出的业务异常。"""


# ------------------------------------------------------------------ 校验函数
def parse_date(raw: str, today: Optional[date] = None) -> str:
    """解析日期输入，返回 ``YYYY-MM-DD`` 字符串。

    支持 ``YYYY-MM-DD``、``YYYY/M/D``、``YYYY.M.D`` 三种写法；
    也支持省略年份的 ``MM-DD``（按今年补全）；
    空白输入默认返回今天。

    :raises RecordError: 格式非法或日期不存在。
    """
    text = (raw or "").strip()
    base = today or date.today()
    if not text:
        return base.isoformat()

    match = _DATE_PATTERN.match(text)
    if match:
        year, month, day = (int(g) for g in match.groups())
    else:
        short = _SHORT_DATE_PATTERN.match(text)
        if not short:
            raise RecordError(f"日期格式非法：{raw!r}，正确示例 2026-09-21")
        year = base.year
        month, day = (int(g) for g in short.groups())

    try:
        parsed = date(year, month, day)
    except ValueError as exc:  # 例如 2026-02-30
        raise RecordError(f"日期不存在：{raw!r}（{exc}）") from exc
    if parsed > base + timedelta(days=1):
        raise RecordError(f"日期不能晚于今天：{parsed.isoformat()}")
    return parsed.isoformat()


def parse_positive_int(raw: str, field_name: str) -> int:
    """解析正整数输入。

    :raises RecordError: 非数字或小于等于 0。
    """
    text = str(raw).strip()
    if not text.isdigit():
        raise RecordError(f"{field_name}必须是非负整数，当前输入：{raw!r}")
    value = int(text)
    if value <= 0:
        raise RecordError(f"{field_name}必须大于 0，当前输入：{value}")
    return value


def parse_non_negative_int(raw: str, field_name: str, upper: Optional[int] = None) -> int:
    """解析非负整数输入，可用 ``upper`` 限定上限。

    :raises RecordError: 非数字、为负或超出上限。
    """
    text = str(raw).strip()
    if not text.isdigit():
        raise RecordError(f"{field_name}必须是非负整数，当前输入：{raw!r}")
    value = int(text)
    if upper is not None and value > upper:
        raise RecordError(f"{field_name}不能超过 {upper}，当前输入：{value}")
    return value


def parse_duration(raw: str) -> int:
    """解析用时输入，统一返回秒数。

    支持 ``"25:30"``（分:秒）、``"1:05:00"``（时:分:秒）与 ``"1500"``（纯秒）。
    """
    text = str(raw).strip()
    if not text:
        raise RecordError("用时不能为空，请输入如 12:30 或 1500")

    if text.isdigit():
        seconds = int(text)
    else:
        match = _DURATION_COLON.match(text)
        if not match:
            raise RecordError(f"用时格式非法：{raw!r}，正确示例 12:30 或 1:05:00")
        first, second, third = match.groups()
        if third is None:  # mm:ss
            seconds = int(first) * 60 + int(second)
        else:  # hh:mm:ss
            seconds = int(first) * 3600 + int(second) * 60 + int(third)

    if seconds <= 0:
        raise RecordError("用时必须大于 0 秒")
    if seconds > 24 * 3600:
        raise RecordError("单次练习用时不应超过 24 小时，请检查输入")
    return seconds


def format_duration(seconds: int) -> str:
    """把秒数格式化为 ``mm:ss`` 或 ``h:mm:ss``。"""
    seconds = int(seconds)
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def evaluate(total: int, correct: int, duration_seconds: int) -> dict:
    """计算一次练习的派生指标。

    :return: 含 accuracy / seconds_per_question / speed_level 的字典。
    """
    accuracy = correct / total if total else 0.0
    per_question = duration_seconds / total if total else 0.0
    if per_question <= config.TARGET_SECONDS_PER_QUESTION:
        speed_level = "优秀"
    elif per_question <= config.SLOW_QUESTION_SECONDS:
        speed_level = "正常"
    else:
        speed_level = "偏慢"
    return {
        "accuracy": accuracy,
        "accuracy_percent": round(accuracy * 100, 2),
        "seconds_per_question": round(per_question, 2),
        "speed_level": speed_level,
        "is_slow": per_question > config.SLOW_QUESTION_SECONDS,
    }


# ------------------------------------------------------------------ 服务类
class RecordService:
    """成绩录入服务：校验 -> 落库 -> 反馈。"""

    def __init__(self, db: Database) -> None:
        self.db = db

    # -------------------------------------------------------- 字典读取
    def modules(self) -> List[Module]:
        """返回可选模块列表。"""
        return self.db.list_modules()

    def topics(self, module_id: int) -> List[Topic]:
        """返回指定模块下的考点列表。"""
        return self.db.list_topics(module_id)

    def match_module(self, raw: str) -> Module:
        """按序号或名称匹配模块。

        :raises RecordError: 未匹配到模块。
        """
        text = str(raw).strip()
        modules = self.modules()
        if not modules:
            raise RecordError("模块字典为空，请先执行数据库初始化")
        if text.isdigit():
            index = int(text) - 1
            if 0 <= index < len(modules):
                return modules[index]
            raise RecordError(f"模块序号超出范围：{text}，有效范围 1-{len(modules)}")
        for module in modules:
            if module.name == text:
                return module
        raise RecordError(f"未找到模块：{raw!r}，可选：{'、'.join(m.name for m in modules)}")

    def match_topic(self, module_id: int, raw: str) -> Optional[Topic]:
        """按序号或名称匹配考点；空输入返回 ``None``（表示不细分考点）。"""
        text = str(raw).strip()
        if not text or text in {"-", "0"}:
            return None
        topics = self.topics(module_id)
        if text.isdigit():
            index = int(text) - 1
            if 0 <= index < len(topics):
                return topics[index]
            raise RecordError(f"考点序号超出范围：{text}，有效范围 1-{len(topics)}")
        for topic in topics:
            if topic.name == text:
                return topic
        # 允许自定义考点，直接落库，体现 "考点可扩展"
        topic_id = self.db.add_topic(module_id, text)
        return self.db.get_topic_by_name(module_id, text) if topic_id else None

    # -------------------------------------------------------- 核心流程
    def submit(
        self,
        module_raw: str,
        total_raw: str,
        correct_raw: str,
        duration_raw: str,
        topic_raw: str = "",
        date_raw: str = "",
        note: str = "",
        is_wrong: bool = False,
    ) -> PracticeRecord:
        """校验并保存一次练习记录。

        :param is_wrong: 是否标记为错题/难题，供复盘清单优先推荐。
        :raises RecordError: 任一字段非法。
        """
        module = self.match_module(module_raw)
        total = parse_positive_int(total_raw, "总题数")
        correct = parse_non_negative_int(correct_raw, "对题数", upper=total)
        duration = parse_duration(duration_raw)
        record_date = parse_date(date_raw)
        topic = self.match_topic(module.id, topic_raw)

        record_id = self.db.add_record(
            record_date=record_date,
            module_id=module.id,
            total_questions=total,
            correct_questions=correct,
            duration_seconds=duration,
            topic_id=topic.id if topic else None,
            note=note,
            is_wrong=is_wrong,
        )
        record = self.db.get_record(record_id)
        if record is None:  # pragma: no cover - 仅防御性分支
            raise RecordError("记录写入失败，请重试")
        return record

    def recent(self, limit: int = 10) -> List[PracticeRecord]:
        """返回最近的练习记录。"""
        return self.db.list_records(limit=limit)

    def remove(self, record_id: int) -> bool:
        """删除指定记录。"""
        return self.db.delete_record(record_id)


def build_feedback(record: PracticeRecord) -> str:
    """把一条记录渲染为面向用户的即时反馈文本。"""
    metrics = evaluate(
        record.total_questions, record.correct_questions, record.duration_seconds
    )
    lines = [
        f"已保存：{record.record_date} | {record.module_name}"
        + (f" / {record.topic_name}" if record.topic_name else "")
        + ("  [已标记错题]" if record.is_wrong else ""),
        f"题数 {record.correct_questions}/{record.total_questions}，"
        f"正确率 {metrics['accuracy_percent']}%，"
        f"单题耗时 {metrics['seconds_per_question']}s（{metrics['speed_level']}）",
    ]
    if record.is_wrong:
        lines.append("提示：该考点已进入复盘清单，可用 python -m src.main review 查看优先级。")
    if metrics["is_slow"]:
        lines.append(
            f"提示：单题耗时超过 {int(config.SLOW_QUESTION_SECONDS)}s，"
            "建议复盘该模块的解题步骤"
        )
    return "\n".join(lines)
