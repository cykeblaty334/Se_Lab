# -*- coding: utf-8 -*-
"""成绩录入模块单元测试：重点覆盖输入校验的异常场景。"""

from datetime import date

import pytest

from src.recorder import (
    RecordError,
    RecordService,
    build_feedback,
    evaluate,
    format_duration,
    parse_date,
    parse_duration,
    parse_non_negative_int,
    parse_positive_int,
)


# ------------------------------------------------------------------ 日期解析
@pytest.mark.parametrize(
    "raw, expected",
    [
        ("2026-09-21", "2026-09-21"),
        ("2026/9/21", "2026-09-21"),
        ("2026.9.21", "2026-09-21"),
        ("", "2026-09-21"),  # 留空取基准日期，而非真实运行日期
        ("  2026-01-05  ", "2026-01-05"),
    ],
)
def test_parse_date_valid(raw, expected):
    assert parse_date(raw, today=date(2026, 9, 21)) == expected


def test_parse_date_short_form_uses_current_year():
    assert parse_date("03-08", today=date(2026, 9, 21)) == "2026-03-08"


@pytest.mark.parametrize("raw", ["2026-13-01", "2026-02-30", "hello", "2026/9", "20260921"])
def test_parse_date_invalid(raw):
    with pytest.raises(RecordError):
        parse_date(raw, today=date(2026, 9, 21))


def test_parse_date_rejects_future_date():
    with pytest.raises(RecordError, match="不能晚于今天"):
        parse_date("2027-01-01", today=date(2026, 9, 21))


# ------------------------------------------------------------------ 数值解析
@pytest.mark.parametrize("raw, expected", [("20", 20), ("1", 1), (" 35 ", 35)])
def test_parse_positive_int_valid(raw, expected):
    assert parse_positive_int(raw, "总题数") == expected


@pytest.mark.parametrize("raw", ["0", "-5", "abc", "", "1.5"])
def test_parse_positive_int_invalid(raw):
    with pytest.raises(RecordError):
        parse_positive_int(raw, "总题数")


def test_parse_non_negative_int_upper_bound():
    assert parse_non_negative_int("20", "对题数", upper=20) == 20
    with pytest.raises(RecordError, match="不能超过"):
        parse_non_negative_int("21", "对题数", upper=20)
    with pytest.raises(RecordError):
        parse_non_negative_int("-1", "对题数")


# ------------------------------------------------------------------ 用时解析
@pytest.mark.parametrize(
    "raw, expected",
    [("1500", 1500), ("25:00", 1500), ("1:05:00", 3900), ("0:45", 45), ("10:00", 600)],
)
def test_parse_duration_valid(raw, expected):
    assert parse_duration(raw) == expected


@pytest.mark.parametrize("raw", ["", "abc", "25:75", "0", "0:00", "25:00:99"])
def test_parse_duration_invalid(raw):
    with pytest.raises(RecordError):
        parse_duration(raw)


def test_parse_duration_rejects_unreasonable_input():
    with pytest.raises(RecordError, match="24 小时"):
        parse_duration("25:00:00")


@pytest.mark.parametrize(
    "seconds, expected", [(45, "00:45"), (1500, "25:00"), (3900, "1:05:00")]
)
def test_format_duration(seconds, expected):
    assert format_duration(seconds) == expected


# ------------------------------------------------------------------ 指标计算
def test_evaluate_metrics():
    metrics = evaluate(total=20, correct=15, duration_seconds=600)
    assert metrics["accuracy"] == pytest.approx(0.75)
    assert metrics["accuracy_percent"] == 75.0
    assert metrics["seconds_per_question"] == 30.0
    assert metrics["speed_level"] == "优秀"
    assert metrics["is_slow"] is False


@pytest.mark.parametrize(
    "per_question, level",
    [(45.0, "优秀"), (46.0, "正常"), (60.0, "正常"), (61.0, "偏慢")],
)
def test_evaluate_speed_level_boundary(per_question, level):
    metrics = evaluate(total=10, correct=5, duration_seconds=int(per_question * 10))
    assert metrics["speed_level"] == level


def test_evaluate_zero_total_is_safe():
    """总题数为 0 时不得抛 ZeroDivisionError。"""
    metrics = evaluate(total=0, correct=0, duration_seconds=0)
    assert metrics["accuracy"] == 0.0
    assert metrics["seconds_per_question"] == 0.0


# ------------------------------------------------------------------ 服务类
def test_match_module_by_index_and_name(seeded_db):
    service = RecordService(seeded_db)
    assert service.match_module("1").name == "言语理解与表达"
    assert service.match_module("数量关系").code == "SHULIANG"


@pytest.mark.parametrize("raw", ["99", "不存在的模块", ""])
def test_match_module_invalid(seeded_db, raw):
    with pytest.raises(RecordError):
        RecordService(seeded_db).match_module(raw)


def test_match_topic_blank_returns_none(seeded_db):
    service = RecordService(seeded_db)
    module = service.match_module("资料分析")
    assert service.match_topic(module.id, "") is None
    assert service.match_topic(module.id, "2").name == "隔年增长率"


def test_match_topic_creates_custom_topic(seeded_db):
    """自定义考点应被自动落库，体现考点可扩展。"""
    service = RecordService(seeded_db)
    module = service.match_module("资料分析")
    topic = service.match_topic(module.id, "年均增长率")
    assert topic is not None and topic.name == "年均增长率"
    assert service.match_topic(module.id, "年均增长率").id == topic.id


def test_submit_persists_record(seeded_db):
    service = RecordService(seeded_db)
    record = service.submit(
        module_raw="数量关系",
        total_raw="20",
        correct_raw="9",
        duration_raw="25:30",
        topic_raw="行程问题",
        date_raw="2026-09-15",
        note="专项突破",
    )
    assert record.id is not None
    assert record.module_name == "数量关系"
    assert record.topic_name == "行程问题"
    assert record.duration_seconds == 1530
    assert seeded_db.count_records() == 1


def test_submit_rejects_correct_greater_than_total(seeded_db):
    service = RecordService(seeded_db)
    with pytest.raises(RecordError, match="不能超过"):
        service.submit("数量关系", "10", "11", "10:00")
    assert seeded_db.count_records() == 0


def test_submit_rejects_illegal_module(seeded_db):
    service = RecordService(seeded_db)
    with pytest.raises(RecordError):
        service.submit("申论", "10", "5", "10:00")


def test_service_recent_and_remove(seeded_db):
    service = RecordService(seeded_db)
    record = service.submit("常识判断", "10", "5", "05:00")
    assert len(service.recent(limit=5)) == 1
    assert service.remove(record.id) is True
    assert service.recent(limit=5) == []


def test_build_feedback_contains_slow_hint(seeded_db):
    service = RecordService(seeded_db)
    slow = service.submit("数量关系", "20", "10", "40:00")  # 单题 120s
    feedback = build_feedback(slow)
    assert "已保存" in feedback
    assert "偏慢" in feedback
    assert "建议复盘" in feedback

    fast = service.submit("常识判断", "20", "18", "05:00")
    assert "建议复盘" not in build_feedback(fast)
