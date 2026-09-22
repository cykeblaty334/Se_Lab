# -*- coding: utf-8 -*-
"""复盘推荐模块单元测试：错题标记、优先级计算与复盘清单渲染。"""

from datetime import date

import pytest

from src import config
from src.reviewer import ReviewService, build_reason, priority_score

TODAY = date(2026, 9, 21)


@pytest.fixture()
def review_db(seeded_db):
    """写入带考点、带错题标记的样本数据（日期相对 TODAY 前移）。"""
    modules = {module.name: module for module in seeded_db.list_modules()}
    dataset = [
        # (日期, 模块, 考点, 总题数, 对题数, 用时, 是否错题)
        ("2026-09-12", "数量关系", "行程问题", 20, 6, 2000, True),
        ("2026-09-13", "数量关系", "行程问题", 10, 3, 900, True),
        ("2026-09-14", "资料分析", "增长率", 20, 13, 1500, False),
        ("2026-09-15", "言语理解与表达", "逻辑填空", 20, 17, 700, False),
        ("2026-09-16", "常识判断", "法律常识", 20, 10, 500, False),
    ]
    for record_date, module_name, topic_name, total, correct, duration, wrong in dataset:
        module = modules[module_name]
        topic = seeded_db.get_topic_by_name(module.id, topic_name)
        seeded_db.add_record(
            record_date=record_date,
            module_id=module.id,
            topic_id=topic.id if topic else None,
            total_questions=total,
            correct_questions=correct,
            duration_seconds=duration,
            note="复盘样本",
            is_wrong=wrong,
        )
    return seeded_db


# ------------------------------------------------------------------ 优先级算法
def test_priority_increases_with_wrong_records():
    base = priority_score(0, 0.6, 45.0)
    assert priority_score(3, 0.6, 45.0) > base


def test_priority_increases_when_accuracy_drops():
    assert priority_score(0, 0.3, 45.0) > priority_score(0, 0.8, 45.0)


def test_priority_increases_when_slower_than_target():
    fast = priority_score(0, 0.6, config.TARGET_SECONDS_PER_QUESTION)
    slow = priority_score(0, 0.6, config.TARGET_SECONDS_PER_QUESTION * 3)
    assert slow > fast


def test_priority_does_not_reward_being_fast():
    """比目标更快不会再加分（速度只作为扣分项存在）。"""
    at_target = priority_score(1, 0.5, config.TARGET_SECONDS_PER_QUESTION)
    faster = priority_score(1, 0.5, config.TARGET_SECONDS_PER_QUESTION / 2)
    assert faster == at_target


def test_priority_clamps_broken_accuracy():
    """正确率超出 [0,1] 时应被夹紧，不产生异常加权。"""
    assert priority_score(0, 5.0, 45.0) == priority_score(0, 1.0, 45.0)
    assert priority_score(0, -1.0, 45.0) == priority_score(0, 0.0, 45.0)


def test_priority_is_rounded():
    assert priority_score(1, 0.5, 60.0) == round(priority_score(1, 0.5, 60.0), 2)


# ------------------------------------------------------------------ 原因描述
def test_reason_mentions_wrong_count():
    assert "错题 2 条" in build_reason(2, 0.5, 40.0)


def test_reason_mentions_accuracy():
    assert "正确率 50.0%" in build_reason(0, 0.5, 40.0)


def test_reason_flags_slow_topic():
    assert "偏慢" in build_reason(0, 0.5, config.SLOW_QUESTION_SECONDS + 20)


def test_reason_flags_slightly_slow_topic():
    assert "略慢" in build_reason(0, 0.5, config.TARGET_SECONDS_PER_QUESTION + 1)


def test_reason_omits_speed_when_fast():
    reason = build_reason(0, 0.5, config.TARGET_SECONDS_PER_QUESTION)
    assert "偏慢" not in reason and "略慢" not in reason


# ------------------------------------------------------------------ 清单生成
def test_review_items_ranked_by_priority(review_db):
    items = ReviewService(review_db).review_items(days=30, top_n=3, today=TODAY)
    assert len(items) == 3
    # 行程问题错题 2 条且正确率最低，应排第一
    assert items[0].topic_name == "行程问题"
    assert items[0].wrong_records == 2
    assert items[0].accuracy == pytest.approx(0.3, abs=0.01)
    assert items[0].priority > items[-1].priority


def test_review_items_computes_derived_metrics(review_db):
    items = ReviewService(review_db).review_items(days=30, top_n=1, today=TODAY)
    first = items[0]
    assert first.total_questions == 30  # 两次练习累加
    assert first.correct_questions == 9
    assert first.seconds_per_question == pytest.approx(96.67, abs=0.01)
    assert first.reason


def test_review_items_respects_top_n(review_db):
    assert len(ReviewService(review_db).review_items(days=30, top_n=1, today=TODAY)) == 1
    # 4 个考点中「逻辑填空」无错题、正确率 85%、35s/题，三个维度都正常，不占用名额
    assert len(ReviewService(review_db).review_items(days=30, top_n=9, today=TODAY)) == 3


def test_review_items_skips_healthy_topic(review_db):
    """状态正常的考点不应为了凑满条数被推荐。"""
    items = ReviewService(review_db).review_items(days=30, top_n=9, today=TODAY)
    assert "逻辑填空" not in {item.topic_name for item in items}


@pytest.mark.parametrize(
    "wrong, accuracy, seconds, expected",
    [
        (0, 1.0, config.TARGET_SECONDS_PER_QUESTION, False),   # 三维全正常
        (1, 1.0, config.TARGET_SECONDS_PER_QUESTION, True),    # 有错题
        (0, 0.5, 20.0, True),                                  # 正确率低于门槛
        (0, 1.0, config.TARGET_SECONDS_PER_QUESTION + 1, True),  # 单题耗时超标
    ],
)
def test_is_worth_reviewing(wrong, accuracy, seconds, expected):
    from src.reviewer import is_worth_reviewing

    assert is_worth_reviewing(wrong, accuracy, seconds) is expected


def test_is_worth_reviewing_boundary_on_accuracy():
    """正确率恰好等于门槛时判为正常。"""
    from src.reviewer import is_worth_reviewing

    assert is_worth_reviewing(0, config.REVIEW_ACCURACY_FLOOR, 30.0) is False
    assert is_worth_reviewing(0, config.REVIEW_ACCURACY_FLOOR - 0.01, 30.0) is True


def test_review_items_excludes_records_outside_window(review_db):
    """窗口外的记录不应参与推荐。"""
    assert ReviewService(review_db).review_items(days=1, top_n=3, today=TODAY) == []


def test_review_items_returns_empty_without_topic_records(seeded_db):
    modules = seeded_db.list_modules()
    seeded_db.add_record(
        record_date=TODAY.isoformat(),
        module_id=modules[0].id,
        total_questions=10,
        correct_questions=8,
        duration_seconds=400,
        topic_id=None,  # 未填考点 -> 无法定位复盘对象
    )
    assert ReviewService(seeded_db).review_items(days=30, top_n=3, today=TODAY) == []


def test_review_items_attaches_knowledge_references(review_db):
    """复盘条目应带上知识库卡片，方便立刻回顾公式。"""
    items = ReviewService(review_db).review_items(days=30, top_n=3, today=TODAY)
    by_topic = {item.topic_name: item for item in items}
    assert any("行程问题" in ref for ref in by_topic["行程问题"].references)
    assert all(ref.startswith("【") for ref in by_topic["行程问题"].references)


def test_references_for_unknown_topic_is_empty(review_db):
    assert ReviewService(review_db).references_for("不存在的考点") == []


def test_references_for_blank_topic_is_empty(review_db):
    assert ReviewService(review_db).references_for("") == []


# ------------------------------------------------------------------ 错题标记
def test_mark_and_clear_wrong_flag(review_db):
    service = ReviewService(review_db)
    records = review_db.list_records()
    target = records[0]
    assert target.is_wrong is False

    assert service.mark(target.id, is_wrong=True).is_wrong is True
    assert review_db.count_wrong_records() == 3

    assert service.mark(target.id, is_wrong=False).is_wrong is False
    assert review_db.count_wrong_records() == 2


def test_mark_missing_record_returns_none(review_db):
    assert ReviewService(review_db).mark(99999) is None


def test_wrong_records_lists_only_flagged(review_db):
    records = ReviewService(review_db).wrong_records(limit=10)
    assert len(records) == 2
    assert all(record.is_wrong for record in records)


# ------------------------------------------------------------------ 文本渲染
def test_format_list_renders_topics_and_hint(review_db):
    text = ReviewService(review_db).format_list(days=30, top_n=3, today=TODAY)
    assert "今日优先复盘清单" in text
    assert "累计错题 2 条" in text
    assert "行程问题" in text
    assert "知识卡片：" in text
    assert "python -m src.main quiz" in text


def test_format_list_includes_quiz_weak_keywords(review_db):
    review_db.add_quiz_log("排列组合", "公式", "不会", 20.0, False)
    text = ReviewService(review_db).format_list(days=30, top_n=3, today=TODAY)
    assert "闪卡抽测薄弱点" in text
    assert "排列组合" in text


def test_format_list_without_data_gives_guidance(seeded_db):
    text = ReviewService(seeded_db).format_list(days=30, top_n=3, today=TODAY)
    assert "暂无带考点的练习记录" in text


def test_format_list_respects_days_scope(review_db):
    assert "暂无带考点的练习记录" in ReviewService(review_db).format_list(
        days=1, top_n=3, today=TODAY
    )


def test_format_list_reports_when_all_topics_healthy(seeded_db):
    """所有考点状态正常时说明原因，而不是列健康考点凑数。"""
    modules = {module.name: module for module in seeded_db.list_modules()}
    module = modules["言语理解与表达"]
    topic = seeded_db.get_topic_by_name(module.id, "逻辑填空")
    seeded_db.add_record(
        record_date="2026-09-15",
        module_id=module.id,
        topic_id=topic.id,
        total_questions=20,
        correct_questions=19,
        duration_seconds=500,
    )
    service = ReviewService(seeded_db)
    assert service.review_items(days=30, top_n=3, today=TODAY) == []
    text = service.format_list(days=30, top_n=3, today=TODAY)
    assert "均未触发复盘条件" in text
    assert "暂无带考点的练习记录" not in text


def test_as_dicts_returns_export_ready_rows(review_db):
    rows = ReviewService(review_db).as_dicts(days=30, top_n=2, today=TODAY)
    assert len(rows) == 2
    assert set(rows[0]) == {
        "topic_name",
        "module_name",
        "priority",
        "reason",
        "accuracy",
        "seconds_per_question",
        "wrong_records",
    }
    assert rows[0]["topic_name"] == "行程问题"
